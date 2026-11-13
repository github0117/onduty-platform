# 任务清单：L5 效率账本

关联规格：[spec.md](./spec.md)

## 阶段 1：数据层

- [x] T1 确认迁移 head
  - 运行 `cd apps/api && uv run alembic heads`，记录当前 head 作为 `down_revision`。
- [x] T2 新增模型 `apps/api/src/ticket_agent/efficiency/models.py`
  - `EfficiencyAssumption`、`EfficiencyLedgerEntry`，含唯一约束与两个索引。
- [x] T3 新增 `apps/api/src/ticket_agent/efficiency/__init__.py`
- [x] T4 新增迁移 `apps/api/migrations/versions/<rev>_efficiency_ledger.py`
  - 建两张表、唯一约束、索引；实现 `downgrade`。
  - 在真实 PostgreSQL 执行 upgrade，检查 head 与表结构。

## 阶段 2：服务层

- [x] T5 新增 `apps/api/src/ticket_agent/efficiency/schemas.py`
  - `AssumptionView`、`AssumptionUpdate`、`EfficiencySummary`、`SourceBreakdown`、
    `EmployeeBreakdown`、`DailyPoint`、`LedgerEntryView`、`LedgerPage`、
    `MaterializeResult`、`RebuildRequest`。
- [x] T6 新增 `apps/api/src/ticket_agent/efficiency/service.py`
  - `assumptions_for`、`update_assumptions`、`materialize`、`summary`、`ledger`、
    `materialize_active_business_units`。
  - 物化使用保存点 + `IntegrityError` 兜底。
  - 汇总口径严格按 spec 第 2 节；模型成本只从 `model_calls` 取一次。
- [x] T7 `apps/api/src/ticket_agent/shared/settings.py` 新增 5 个默认配置项
- [x] T8 `.env.example` 同步 5 个配置项

## 阶段 3：接口与调度

- [x] T9 新增 `apps/api/src/ticket_agent/efficiency/router.py`
  - GET summary / ledger / assumptions，PUT assumptions，POST rebuild。
  - 读用 `ensure_metrics_viewer`，写用 `operations.manage` 校验 + `record_audit`。
- [x] T10 `apps/api/src/ticket_agent/main.py`
  - 注册 `efficiency_router`（前缀 `/api/v1`）。
  - 新增 beat 任务 `materialize_efficiency_ledger`，每 300 秒。
- [x] T11 新增 `apps/api/src/ticket_agent/efficiency/worker.py`
  - Celery 任务 + `system_session()`，窗口最近 2 天。

## 阶段 4：前端

- [x] T12 `apps/web/src/api.ts` 新增 5 个请求函数与类型
- [x] T13 新增 `apps/web/src/EfficiencyPage.tsx`
  - 指标卡、来源/员工/每日明细、假设表单、账本分页、重算按钮、空态与错误态。
- [x] T14 `apps/web/src/App.tsx`
  - `routeMeta["/efficiency"]`、lazy import、`platformChildren`、条件渲染。
- [x] T15 `apps/web/src/capabilities.ts`
  - `pathCapabilities` 增加 `/efficiency` → `operations.view`。

## 阶段 5：测试

- [x] T16 新增 `apps/api/tests/integration/test_efficiency_ledger.py`
  - 覆盖 spec 验收矩阵 1–3、5–9、11–12。
- [x] T17 新增 `apps/api/tests/integration/test_efficiency_ledger_pg.py`
  - 真实 PostgreSQL 并发物化（矩阵 4），缺 `TEST_POSTGRES_URL` 时 skip。
- [x] T18 新增前端冒烟或用例
  - 至少验证 `/efficiency` 直达、保存假设、重算按钮反馈。

## 阶段 6：验收与记录

- [x] T19 专项测试、全量 pytest、Ruff、mypy、tsc、vite build
- [x] T20 `make migrate-check`、`make stack-smoke`
- [x] T21 真实服务 + 浏览器验收 `/efficiency`，清理临时数据
- [x] T22 更新 `outputs/07_开发日志.md`
- [x] T23 更新 `outputs/06_当前实施状态.md`
- [x] T24 更新 `docs/features.md` 与 README 相关章节（如涉及）

## 完成定义

- 验收矩阵 15 项全部有实测记录，异常路径包含拒绝与回滚。
- 迁移在真实 PostgreSQL 可 upgrade/downgrade，head 正确。
- 页面无手工刷新依赖，重复操作不产生重复账本行。
- 最终回复列明实测路径、验收数据、外部依赖未验收项与剩余风险。
