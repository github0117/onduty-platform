# L5 效率账本（人时 / 成本 / ROI）

状态：待审批  
日期：2026-11-11

## 1. 背景与目标

平台已有 `model_calls`（token 与 `estimated_cost`）以及
`GET /api/v1/customer-service/value-metrics`（草稿采纳率、单会话成本），
但缺少把「数字员工省下多少人工」与「花了多少模型成本」放在同一口径下核算的账本。

本规格补齐 L5 效率账本：

- 按业务单元固化每条「已完成的数字员工产出」对应的人工工时节省。
- 在记录工时节省时冻结当时使用的人力成本假设，后续改参数不追溯历史。
- 汇总模型成本，计算 ROI、净收益、人时节省，并按来源、员工、日期拆分。
- 提供可重复执行的物化（materialize）能力，保证幂等与并发安全。
- 提供页面查看与参数维护，管理员可手动重算窗口。

不在本期范围：

- 不接入真实 HR 薪酬系统、财务系统或工时填报系统。
- 不做按人天/排班的产能规划。
- 不回溯改写已生成的历史账本条目。
- 不覆盖电商视频渲染、图片生成等非任务型产出的单独计价。

## 2. 计量口径（必须与页面文案一致）

账本只记录「数字员工独立完成、未被人工接管」的产出，单位为人时（分钟）。

| 来源类型 | 计入条件 | 单条节省 |
| --- | --- | --- |
| `TICKET_AUTO_RESOLVED` | 工单 `workflow_state = COMPLETED` 且 `status ∈ {RESOLVED, CLOSED}`，`updated_at` 落在窗口内 | `minutes_per_ticket` |
| `CONVERSATION_RESOLVED` | 会话 `status = RESOLVED`，`assigned_agent_id IS NULL`（无人接管），且 `current_ticket_id` 为空或不指向已计入工单；`updated_at` 落在窗口内 | `minutes_per_conversation` |
| `ECOMMERCE_LISTING_COMPLETED` | 上架任务 `status ∈ {SUCCEEDED, PUBLISHED}`，`updated_at` 落在窗口内 | `minutes_per_listing` |

去重规则：

- 每个 `(business_unit_id, source_type, source_id)` 只允许一条账本记录，由数据库唯一约束兜底。
- 会话若关联到某张已计入的工单，不重复计入人工时。
- 同一对象状态反复变化只更新业务表，不新增账本行；已生成的账本行不可变。

成本口径：

- 人工成本节省 = `human_minutes_saved / 60 * hourly_labor_cost`，四舍五入到 4 位小数。
- 模型成本 = 同业务单元、同窗口内 `model_calls.status = 'SUCCEEDED'` 的
  `estimated_cost` 之和；不按账本条目重复分摊，避免双计。
- ROI 倍数 = 人工成本节省 / 模型成本；模型成本为 0 时返回 `null`，不以 0 或无穷大冒充。
- 净收益 = 人工成本节省 - 模型成本。
- 人时 = 分钟 / 60，保留 2 位小数。

币种：默认 `CNY`，按业务单元假设保存，汇总时若窗口内出现多币种则返回
`mixed_currency=true` 并只对同币种金额做加减，不静默混算。

## 3. 数据模型

新增迁移 `apps/api/migrations/versions/<new_rev>_efficiency_ledger.py`，
`down_revision` 取实现时 `alembic heads` 的当前 head。

### 3.1 `efficiency_assumptions`

| 列 | 类型 | 约束 |
| --- | --- | --- |
| `id` | Uuid | PK |
| `business_unit_id` | String(64) | NOT NULL, UNIQUE |
| `currency` | String(8) | NOT NULL, 默认 `CNY` |
| `hourly_labor_cost` | Numeric(12,4) | NOT NULL, > 0 |
| `minutes_per_ticket` | Numeric(10,2) | NOT NULL, >= 0 |
| `minutes_per_conversation` | Numeric(10,2) | NOT NULL, >= 0 |
| `minutes_per_listing` | Numeric(10,2) | NOT NULL, >= 0 |
| `version` | Integer | NOT NULL, 默认 1 |
| `updated_by` | String(128) | NOT NULL |
| `created_at` / `updated_at` | DateTime(timezone=True) | NOT NULL |

默认值（未写入数据库时由服务层返回）：`CNY`、`60.0`、`15`、`8`、`20`。

### 3.2 `efficiency_ledger_entries`

| 列 | 类型 | 约束 |
| --- | --- | --- |
| `id` | Uuid | PK |
| `business_unit_id` | String(64) | NOT NULL |
| `employee_id` | Uuid | NULL, FK `digital_employees.id` ON DELETE SET NULL |
| `source_type` | String(40) | NOT NULL |
| `source_id` | Uuid | NOT NULL |
| `occurred_at` | DateTime(timezone=True) | NOT NULL |
| `human_minutes_saved` | Numeric(10,2) | NOT NULL, >= 0 |
| `labor_cost_saved` | Numeric(12,4) | NOT NULL, >= 0 |
| `currency` | String(8) | NOT NULL |
| `assumption_snapshot` | JSON | NOT NULL |
| `created_at` | DateTime(timezone=True) | NOT NULL |

约束与索引：

- `UniqueConstraint(business_unit_id, source_type, source_id, name="uq_efficiency_ledger_source")`
- `Index("ix_efficiency_ledger_unit_occurred", business_unit_id, occurred_at)`
- `Index("ix_efficiency_ledger_unit_employee", business_unit_id, employee_id)`

`assumption_snapshot` 至少包含：`hourly_labor_cost`、对应来源的分钟数、
`currency`、`assumption_version`、`basis`（口径说明字符串）。

## 4. 后端实现

新增包 `apps/api/src/ticket_agent/efficiency/`：

| 文件 | 内容 |
| --- | --- |
| `__init__.py` | 空包标记 |
| `models.py` | `EfficiencyAssumption`、`EfficiencyLedgerEntry` |
| `schemas.py` | Pydantic 响应/请求模型 |
| `service.py` | 假设读取、物化、汇总、明细查询、参数更新 |
| `router.py` | 5 个 HTTP 端点 |
| `worker.py` | 周期物化任务 |

### 4.1 `service.py` 函数契约

- `assumptions_for(session, business_unit_id) -> AssumptionView`
  读取数据库行；不存在时返回默认值且 `persisted=False`。
- `update_assumptions(session, business_unit_id, payload, actor_id) -> AssumptionView`
  校验后 upsert，`version += 1`；非法值抛 `ApiProblem(422, "INVALID_ASSUMPTIONS")`。
- `materialize(session, business_unit_id, from_at, to_at) -> MaterializeResult`
  扫描三类来源，逐条构造账本行，捕获唯一约束冲突后 `rollback` 到保存点并跳过；
  返回 `created` / `skipped_existing` / `skipped_not_eligible` 计数。
- `summary(session, business_unit_id, days) -> EfficiencySummary`
  以账本聚合 + `model_calls` 聚合计算 2.3 节全部指标，附
  `by_source`、`by_employee`、`daily`、`assumptions`、`basis`。
- `ledger(session, business_unit_id, days, limit, offset) -> LedgerPage`
  只读分页，按 `occurred_at DESC, created_at DESC` 排序。
- `materialize_active_business_units(session, now) -> dict[str, int]`
  取最近 7 天有工单/会话/上架任务的业务单元，逐个物化，供 beat 调用。

### 4.2 并发与幂等

- 先 `SELECT` 已存在键集合，再批量插入，减少冲突面。
- 插入使用 `session.begin_nested()` 保存点；捕获 `IntegrityError` 后回滚保存点并计入
  `skipped_existing`。SQLite 与 PostgreSQL 行为一致，不依赖 `ON CONFLICT`。
- 同一窗口重复调用返回 `created` 递减至 0，账本总行数不变。
- 并发 INSERT 由唯一约束兜底，落败方不报 500。

### 4.3 HTTP 端点

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/v1/efficiency/summary` | `operations.view` | `business_unit_id` 可选，`days` 1–365，默认 30 |
| GET | `/api/v1/efficiency/ledger` | `operations.view` | `days`、`limit` 1–200、`offset` |
| GET | `/api/v1/efficiency/assumptions` | `operations.view` | 返回当前生效假设 |
| PUT | `/api/v1/efficiency/assumptions` | `operations.manage` | 更新假设，写审计 |
| POST | `/api/v1/efficiency/rebuild` | `operations.manage` | 手动重算 `days` 窗口，写审计 |

- 租户：统一走 `resolve_business_unit`，非授权跨租户返回 403。
- `days` 非法、假设为负数或零时返回 422，错误码分别为
  `INVALID_WINDOW`、`INVALID_ASSUMPTIONS`。
- PUT 与 rebuild 通过 `record_audit` 写入 `efficiency.assumptions.updated`、
  `efficiency.ledger.rebuilt`。

### 4.4 调度

- `worker.py` 提供 `materialize_efficiency_ledger` Celery 任务，使用
  `system_session()`，窗口取最近 2 天以覆盖迟到完成的对象。
- 在 `apps/api/src/ticket_agent/main.py` 的 Celery beat 配置中新增每 300 秒执行一次。
- `main.py` 注册 `efficiency_router`，前缀 `/api/v1`，标签 `efficiency`。

### 4.5 配置

`shared/settings.py` 新增默认项（仅作为未落库时的兜底，不写入镜像密钥）：

```
EFFICIENCY_CURRENCY=CNY
EFFICIENCY_HOURLY_LABOR_COST=60.0
EFFICIENCY_MINUTES_PER_TICKET=15
EFFICIENCY_MINUTES_PER_CONVERSATION=8
EFFICIENCY_MINUTES_PER_LISTING=20
```

`.env.example` 同步这 5 项；本机 `.env` 不强制新增。

## 5. 前端

新增 `/efficiency` 页面，归入“平台管理”。

| 文件 | 改动 |
| --- | --- |
| `apps/web/src/EfficiencyPage.tsx` | 新增页面 |
| `apps/web/src/App.tsx` | `routeMeta["/efficiency"]`、`platformChildren` 增加“效率账本”、lazy import、条件渲染 |
| `apps/web/src/capabilities.ts` | `pathCapabilities` 增加 `/efficiency` → `operations.view` |
| `apps/web/src/api.ts` | 5 个请求函数与对应类型 |
| `apps/web/src/types.ts` | 新增账本相关类型（若 api.ts 未集中定义） |

页面结构：

1. 窗口切换（7 / 30 / 90 天）与“重新计算”按钮。
2. 5 张指标卡：人时节省、人力成本节省、模型成本、ROI 倍数、净收益。
3. 来源明细表：来源类型、条数、人时、人力成本。
4. 员工明细表：员工姓名、条数、人时、人力成本；员工缺失显示“未绑定员工”。
5. 每日趋势表：日期、条数、人时、人力成本。
6. 假设设置卡：币种、时薪、各来源分钟数；仅 `operations.manage` 可见可编辑。
7. 账本明细分页表：时间、来源、对象、员工、人时、人力成本、假设版本。

交互要求：

- 重新计算与保存假设按钮必须有 loading，成功后 `message.success` 并自动刷新汇总与明细，
  失败显示后端 detail，不静默吞错。
- 重复点击保存或重新计算不得产生重复账本行；按钮在请求期间禁用。
- 页面首屏加载失败展示可重试的错误态；空数据显示“当前窗口暂无效率记录”。
- 1200px 以下表格横向滚动，不遮挡操作按钮。

## 6. 验收矩阵

| # | 场景 | 期望 |
| --- | --- | --- |
| 1 | 正常主链路 | 造 1 张 AI 完成工单、1 个未接管已解决会话、1 个已发布上架任务，rebuild 后 summary 三类各 1 条，ROI 与手工计算一致 |
| 2 | 重复操作 | 连续 rebuild 同窗口 3 次，账本行数不变，第 2/3 次 `created=0` |
| 3 | 幂等键 | 同对象状态变化后再次 rebuild，不新增行，旧条目金额不变 |
| 4 | 并发 | 真实 PostgreSQL 两个会话同时 materialize 同一窗口，只产生 1 行/来源，无 500 |
| 5 | 未授权 | agent 访问 GET 403；agent PUT/rebuild 403；supervisor GET/PUT/rebuild 200 |
| 6 | 跨租户 | `bu_other` 账号查 `bu_demo` 403；`bu_demo` summary 不含 `bu_other` 数据 |
| 7 | 非法参数 | 负时薪、负分钟数、`days=0`、`days=366` 返回 422 |
| 8 | 人工接管排除 | `workflow_state=TAKEN_OVER` 的工单不计入；有 `assigned_agent_id` 的会话不计入 |
| 9 | 假设快照 | rebuild 后修改时薪，旧条目金额与 `assumption_snapshot` 不变，新条目用新值 |
| 10 | 失败恢复 | 插入冲突被保存点吞掉后事务仍可用，后续条目正常写入 |
| 11 | 旧数据兼容 | 迁移前已有工单/会话/上架任务在迁移后首次 rebuild 可被回填 |
| 12 | 空窗口 | 无数据时所有金额为 0，ROI 为 `null`，页面显示空态 |
| 13 | 前端入口 | `/efficiency` 直接访问 200；旧菜单与旧路由不受影响 |
| 14 | 前端反馈 | 保存、重算、加载失败、重复点击均有 loading/成功/失败反馈，操作后自动刷新 |
| 15 | 对象链路 | 工单 → 账本 → 汇总；会话 → 账本 → 汇总；上架任务 → 账本 → 汇总，逐段核对 |

## 7. 验收命令

```text
cd apps/api && uv run pytest tests/integration/test_efficiency_ledger.py -q
cd apps/api && uv run pytest -q
cd apps/api && uv run ruff check .
cd apps/api && uv run mypy src
cd apps/web && ./node_modules/.bin/tsc --noEmit
cd apps/web && ./node_modules/.bin/vite build
make migrate-check
make stack-smoke
TEST_POSTGRES_URL=postgresql+psycopg://ticket_agent:ticket_agent@127.0.0.1:5432/ticket_agent \
  uv run pytest tests/integration/test_efficiency_ledger_pg.py -q
```

真实服务验收：

- 对运行中的 compose 栈执行 `POST /api/v1/efficiency/rebuild`，再查 summary 与 ledger。
- 浏览器打开 `/efficiency`，验证指标卡、明细、保存假设、重新计算与自动刷新。
- 验收产生的临时业务单元数据（`bu_accept_efficiency*`）结束后清理，残留计数为 0。

## 8. 外部依赖与风险

- 未接入真实薪酬/工时系统，时薪与分钟数来自可配置假设，不是财务口径。
- 模型成本来自 `model_calls.estimated_cost`，是估算值，不是账单。
- 已计入的账本行不可修改；若假设填错，只能停用业务单元或新增版本后重算新窗口，
  历史口径仍保留，需在页面“口径说明”中明确。
- 电商上架任务状态若未来新增成功态，需要同步更新 `ECOMMERCE_LISTING_COMPLETED` 判定。
- 未覆盖图片生成、视频渲染、知识评测等非任务型产出的效率折算。

## 9. 需要确认

1. 三个来源口径（工单 / 会话 / 上架任务）是否认可？
2. 默认假设值（时薪 60 元、工单 15 分钟、会话 8 分钟、上架 20 分钟）是否合适？
3. 账本条目是否接受“生成后不可改，只有新增”？
