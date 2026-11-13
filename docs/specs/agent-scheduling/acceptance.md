# L6 智能排班验收报告

状态：通过（待人工签署）  
验收日期：2026-11-13  
关联文档：[spec.md](./spec.md) · [tasks.md](./tasks.md)

## 1. 验收结论

| 维度 | 结论 | 说明 |
| --- | --- | --- |
| 功能主链路 | 通过 | 班次→周草稿→排班→发布→开启约束→自动分配，在真实运行栈完成 |
| 数据与迁移 | 通过 | 迁移 head `d7a4c2e9f531`，四表与部分唯一索引生效，支持升级/降级 |
| 幂等与并发 | 通过 | 重复保存/发布/克隆不出重复数据；真实 PostgreSQL 并发发布、克隆、派班通过 |
| 权限与租户 | 通过 | 排班读写与策略修改全部要求 `service.admin`，跨业务单元读写被拒绝 |
| 兼容与回退 | 通过 | 策略默认关闭时旧派班规则不变；关闭开关立即恢复旧规则，不回收已分配会话 |
| 前端入口与反馈 | 通过 | 新路径直达可访问，区块、开关、按钮与自动刷新正常 |
| 外部系统 | 未验收 | 未接真实企业 IM、HR 考勤/排班、外部日历；班表仅在平台内部生效 |

本报告中的“通过”均指在真实数据库或真实运行栈上执行过对应路径，不以单元测试或接口存在代替业务流程验收。

## 2. 验收环境

| 项 | 值 |
| --- | --- |
| 代码基线 | `7a28b04` + 本次 L6 工作区改动 |
| 后端 | FastAPI + SQLAlchemy 2.0 + PostgreSQL + Celery Beat |
| 数据库迁移 head | `d7a4c2e9f531` |
| 运行栈 | 本机 compose：API `127.0.0.1:8000`、PostgreSQL、Redis、Celery Beat |
| 前端 | Vite dev server `127.0.0.1:5173` |
| 验收时区 | `Asia/Shanghai` |
| 真实栈验收业务单元 | `bu_accept_sched_11acde`（验收后已清理） |

## 3. 交付物

| 文件 | 内容 |
| --- | --- |
| `apps/api/src/ticket_agent/scheduling/models.py` | 四张表、唯一约束、部分唯一索引、业务索引 |
| `apps/api/src/ticket_agent/scheduling/schemas.py` | 班次、班表、条目、策略、当班响应模型 |
| `apps/api/src/ticket_agent/scheduling/service.py` | 时区换算、校验、保存/发布/克隆、策略、当班查询 |
| `apps/api/src/ticket_agent/scheduling/router.py` | 排班 HTTP 接口、`service.admin`、审计 |
| `apps/api/migrations/versions/d7a4c2e9f531_agent_scheduling.py` | 建表、部分唯一索引、完整 downgrade |
| `apps/api/src/ticket_agent/customer_service/service.py` | 自动分配接入当班约束、候选解释、确定性行锁与锁内负载重算 |
| `apps/web/src/SchedulingPage.tsx` | 主管排班页面 |
| `apps/web/src/App.tsx` / `api.ts` / `types.ts` / `capabilities.ts` | 路由、请求、类型与权限映射 |
| `apps/api/tests/integration/test_agent_scheduling.py` | 13 个专项集成测试 |
| `apps/api/tests/integration/test_agent_scheduling_pg.py` | 3 个真实 PostgreSQL 并发测试 |

## 4. 验收矩阵

| # | 场景 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 正常主链路 | 通过 | 真实栈脚本：3 个班次、8 条条目、发布当前周、开启策略后自动分配选中当班坐席 A，风险/负载/当班解释完整 |
| 2 | 旧规则兼容 | 通过 | `test_auto_assign_respects_published_schedule` 关闭开关后回退旧规则；`test_customer_conversations.py` 全量回归通过 |
| 3 | 不当班拒绝 | 通过 | 真实栈候选明细：坐席 B `on_shift=false`、`eligible=false`、原因“未在已发布班表当班”；会话留在待分配队列 |
| 4 | 边界时间 | 通过 | `test_shift_window_includes_start_excludes_end`：`now=start_at` 当班、`now=end_at` 不当班；跨天班覆盖次日 |
| 5 | 重复保存 | 通过 | `test_draft_validation_versioning_and_idempotent_save`：相同内容重试不增版本、不产生重复条目；内容不同才判 409 |
| 6 | 重复发布 | 通过 | `test_publish_clone_and_archive_shift_snapshot`：重复发布返回同一 PUBLISHED，不新增版本 |
| 7 | 重复克隆/重名 | 通过 | `test_agent_scheduling_pg.py::test_concurrent_clone_creates_one_draft`（另一请求 409）；班次重名由唯一约束拒绝 |
| 8 | 乐观锁 | 通过 | `test_draft_validation_versioning_and_idempotent_save`：旧版本覆盖返回 `ROSTER_VERSION_CONFLICT`，先保存内容未被覆盖 |
| 9 | 并发发布 | 通过 | `test_agent_scheduling_pg.py::test_concurrent_publish_keeps_one_published_row`，3 passed，无 500 |
| 10 | 并发派班 | 通过 | `test_agent_scheduling_pg.py::test_concurrent_auto_assign_does_not_exceed_capacity`，固定顺序行锁 + 锁内重算负载，不超容量 |
| 11 | 未授权 | 通过 | `test_scheduling_endpoints_require_service_admin`：agent 对排班读写和策略修改均 403 |
| 12 | 跨租户 | 通过 | `test_scheduling_is_tenant_scoped`、`test_policy_rows_are_scoped_to_business_unit`：班次/班表/策略跨业务单元读写被拒绝；`test_schedule_policy_is_evaluated_per_business_unit`：A 单元开启约束不影响 B 单元派班 |
| 13 | 非法状态 | 通过 | `test_publish_clone_and_archive_shift_snapshot` 等覆盖：修改 PUBLISHED/ARCHIVED、发布 ARCHIVED、发布空班表均被拒绝 |
| 14 | 非法参数 | 通过 | `test_draft_validation_versioning_and_idempotent_save` 等：非周一、起止相同、非法时区、周外日期、重复坐席日返回 422，整单回滚；`test_dst_nonexistent_and_ambiguous_shift_times_are_rejected`：`America/New_York` 春季不存在时间和秋季歧义时间均 422 且不落条目 |
| 15 | 失败恢复 | 通过 | 同上：一条非法条目导致整单回滚；修正后重试成功；替换发布失败保留旧发布稿 |
| 16 | 模板快照 | 通过 | `test_publish_clone_and_archive_shift_snapshot`：归档模板后原 PUBLISHED 条目 `shift_name`、时间与 `snapshot_json` 不变 |
| 17 | 克隆就绪 | 通过 | 同上：克隆复制条目、快照与跨天时间，源模板停用后仍可直接发布 |
| 18 | 开关恢复 | 通过 | `test_policy_requires_current_week_published_schedule`：无当前周发布稿不能开启；关闭后立即回退旧规则；`test_enforced_policy_does_not_fall_back_without_current_week_roster`：开启后当前周无发布稿时不回退，会话保持未分配并提示缺口 |
| 19 | 不回收进行中会话 | 通过 | `test_auto_assign_respects_published_schedule`：关闭开关后已分配会话仍绑定原当班坐席 |
| 20 | 迁移与旧数据 | 通过 | SQLite 迁移用例 upgrade→downgrade→upgrade；2026-11-13 真实 PostgreSQL `downgrade -1`（`d7a4c2e9f531 → c3e9b1d7a245`）与 `upgrade head` 均成功，`alembic current` 为 `d7a4c2e9f531 (head)`；`make migrate-check` 输出 `at_head` |
| 21 | 前端入口与反馈 | 通过 | 浏览器直达 `/customer-service/scheduling`，区块、开关、按钮可见；历史验收中实际创建班次出现成功提示并自动刷新 |
| 22 | 全对象链路 | 通过 | 真实栈逐段核对：班次模板→草稿条目→发布快照→当班接口→自动分配→数据库计数一致 |

## 5. 自动化检查结果

2026-11-13 实测：

| 命令 | 结果 |
| --- | --- |
| `cd apps/api && uv run pytest tests/integration/test_agent_scheduling.py -q` | `16 passed` |
| `TEST_POSTGRES_URL=... uv run pytest tests/integration/test_agent_scheduling_pg.py -q` | `3 passed` |
| `cd apps/api && uv run pytest -q` | `778 passed, 7 skipped`（跳过项为未设置 `TEST_POSTGRES_URL` 的 PG 专项，已单独执行） |
| `cd apps/api && uv run ruff check .` | `All checks passed!` |
| `cd apps/api && uv run mypy src` | `Success: no issues found in 227 source files` |
| `cd apps/web && ./node_modules/.bin/tsc --noEmit` | 通过（无输出） |
| `cd apps/web && ./node_modules/.bin/vite build` | `✓ built in 2.43s` |
| `make migrate-check` | `migration_preflight=at_head current=d7a4c2e9f531 head=d7a4c2e9f531` |
| 真实 PostgreSQL `alembic downgrade -1` → `upgrade head` | `d7a4c2e9f531 → c3e9b1d7a245` 降级成功，再升级成功，`alembic current` 为 `d7a4c2e9f531 (head)` |
| `make stack-smoke` | 通过：`PENDING_REVIEW → COMPLETED`、sync `SUCCEEDED`、citations 4 |

本轮针对原验收报告中的风险点补强 3 个集成用例：

| 用例 | 覆盖风险 |
| --- | --- |
| `test_dst_nonexistent_and_ambiguous_shift_times_are_rejected` | DST 春季不存在时间、秋季歧义时间返回 422，且失败保存不落任何条目 |
| `test_enforced_policy_does_not_fall_back_without_current_week_roster` | 开启约束后当前周无发布班表时不静默回退，会话保持未分配，当班接口提示覆盖缺口 |
| `test_schedule_policy_is_evaluated_per_business_unit` | 策略按业务单元独立判定，A 单元开启约束不影响 B 单元旧规则派班 |

## 6. 真实栈全链路验收

### 6.1 验收数据

| 对象 | 内容 |
| --- | --- |
| 业务单元 | `bu_accept_sched_11acde` |
| 坐席 A | `accept-sched-a-fbb4`，在线、`ecommerce_aftersales`、R2、容量 5 |
| 坐席 B | `accept-sched-b-*`，在线、同技能、R2、容量 5 |
| 班次模板 | 白班 08:00–18:00；夜班 20:00–04:00（跨天）；全天班 00:00–23:59 |
| 当前周 | 2026-11-09（周一）至 2026-11-15 |
| 班表条目 | 8 条；坐席 A 每天全天班，坐席 B 周一跨天夜班 |
| 会话 | 1 条真实待分配 `CustomerConversation` + 关联工单 |

### 6.2 观测结果

- 草稿保存后 `version=2`，发布后班表状态 `PUBLISHED`。
- 跨天条目：`2026-11-09 20:00 → 2026-11-10 04:00 +08:00`，`snapshot_json.cross_day=true`、`shift_version=1`。
- 策略：`enforce_published_schedule=true`、`persisted=true`、`schedule_ready=true`、`coverage_gap=false`。
- 自动分配选中坐席 A，原因：

```text
当前工单未限定专用技能；风险权限 R2 覆盖 R0；当前负载 0/5；当班 11-13 00:00–11-13 23:59。
```

- 坐席 B 候选：`schedule_enforced=true`、`on_shift=false`、`eligible=false`，排除原因“未在已发布班表当班”。
- 当班接口：`schedule_ready=true`、`coverage_gap=false`，坐席 A 当班、坐席 B 未当班，与候选明细一致。
- 数据库计数（清理前）：shifts 3、rosters 1、entries 8、policies 1、presence 2、conversations 1。

### 6.3 清理

验收结束后按 `bu_accept_sched_%` 前缀清理：

```json
{"shifts": 0, "rosters": 0, "policies": 0, "presence": 0, "conversations": 0}
```

## 7. 异常与拒绝路径

| 路径 | 结果 |
| --- | --- |
| agent 访问排班接口/修改策略 | 403 |
| 跨业务单元读写班次、班表、策略 | 403 或 404，不泄露其他租户数据 |
| 班次重名 | 409 `SHIFT_NAME_CONFLICT` |
| 停用仍被草稿引用的班次 | 409 `SHIFT_IN_USE` |
| 已有草稿时重复克隆 | 409 `ROSTER_DRAFT_EXISTS` |
| 基于旧版本保存不同内容 | 409 `ROSTER_VERSION_CONFLICT` |
| 修改已发布/已归档班表、发布归档稿 | 409 `INVALID_ROSTER_STATE` |
| 非周一、起止时间相同、非法时区 | 422 `INVALID_WEEK` / `INVALID_SHIFT_TIME` |
| 跨租户坐席、周外日期、同一坐席同日重复 | 422 `AGENT_NOT_FOUND` / `INVALID_ROSTER_ENTRY` |
| 发布空班表 | 422 `EMPTY_ROSTER` |
| 无当前周发布稿时开启约束 | 422 `SCHEDULE_NOT_READY` |

## 8. 浏览器验收

- 2026-11-13 复验：直达 `http://127.0.0.1:5173/customer-service/scheduling`，页面显示周范围 `2026-11-09 ~ 2026-11-15`、“周班表”“当前当班坐席”“班次模板”区块、“新增班次”按钮和“按班表约束自动分配”开关；开关默认关闭。
- 2026-11-11 实操作业：在页面创建“浏览器验收班1101”，出现成功提示并自动刷新班次表格，随后清理该班次。
- 旧入口 `/customer-service/admin`、`/customer-service/workbench` 未改动，保持可用。

## 9. 未验收 / 外部依赖

| 项 | 状态 |
| --- | --- |
| 真实企业 IM / 外部排班系统对接 | 未接入，班表只在平台内部生效 |
| HR 考勤、请假、加班、薪酬系统 | 未接入，不参与排班与派班判断 |
| 外部日历 | 未接入 |
| 多业务单元同时在线的全局 Beat 长稳压测 | 未单独长稳压测；多业务单元策略隔离已由 `test_schedule_policy_is_evaluated_per_business_unit` 覆盖 |

## 10. 剩余风险

1. 时区按班表保存的 IANA 名称换算，默认 `Asia/Shanghai`；DST 行为已用 `America/New_York` 覆盖，其他时区的历史规则未逐一枚举。
2. 坐席目录依赖心跳生成的 `agent_presence`，从未登录的坐席不能提前排班。
3. `AgentPresence.agent_id` 当前全局唯一，跨业务单元身份模型限制不在本期重构。
4. 班表只约束自动分配，不等价于考勤，也不强制坐席上下线。
5. 开启约束后若后续周未发布班表，自动分配会持续等待；已用 `test_enforced_policy_does_not_fall_back_without_current_week_roster` 验证不会静默回退，但这是产品行为而非故障修复。
6. 下班不回收进行中会话，这是已批准策略；已分配会话仍需人工处理或按既有规则回收。
7. 全局 Celery Beat 在多业务单元、高并发、长时间运行下的表现未做专项压测；当前验证为并发派班与分单元策略隔离。

## 11. 复验命令

```text
cd apps/api && uv run pytest tests/integration/test_agent_scheduling.py -q
cd apps/api && uv run pytest tests/integration/test_customer_conversations.py -q
cd apps/api && uv run pytest -q
cd apps/api && uv run ruff check .
cd apps/api && uv run mypy src
cd apps/web && ./node_modules/.bin/tsc --noEmit
cd apps/web && ./node_modules/.bin/vite build
make migrate-check
make stack-smoke
TEST_POSTGRES_URL=postgresql+psycopg://ticket_agent:ticket_agent@127.0.0.1:5432/ticket_agent \
  uv run pytest tests/integration/test_agent_scheduling_pg.py -q
```

## 12. 审批签署

| 角色 | 姓名 | 结论 | 日期 |
| --- | --- | --- | --- |
| 开发 |  |  |  |
| 测试 |  |  |  |
| 产品 |  |  |  |
