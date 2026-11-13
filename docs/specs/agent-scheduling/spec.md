# L6 智能排班（人工坐席班表与派班）

状态：待审批  
日期：2026-11-11

## 1. 背景与目标

现有 `AgentPresence` 已记录人工坐席的在线状态、技能、风险权限、最大并发和
自动分配开关；`CustomerConversationService.auto_assign` 已按技能、风险权限和
实时负载分配会话，Celery 每 10 秒执行一次。`workforce` 是数字员工任务编排，
不承载人工坐席排班。

本期在不另建派单系统的前提下补齐：

- 人工坐席班次模板：维护上下班时间、跨天班次和停用状态。
- 周班表：按业务单元、周一到周日编排坐席，支持草稿、发布、修订克隆。
- 快照与不可变发布：已发布班表不受后续班次模板修改影响。
- 业务单元级“按班表约束自动分配”开关，默认关闭以兼容现有数据与演示。
- 自动分配新增“当班”约束，保留在线、技能、风险权限、负载和容量判断。
- 主管页面维护班表、发布/修订、查看当班状态和控制派班开关。

不在本期范围：

- 不预测会话量，不自动生成最优班表，不做求解器。
- 不接入 HR 考勤、请假、加班、薪酬或外部日历。
- 不安排数字员工，不改造 `workforce` 任务编排。
- 不因下班自动回收进行中的会话；下班只阻止新的自动分配。
- 不改变主管手工分配、人工接管和离线回收的既有规则。
- 不新建独立的人力组织目录；首期坐席来自同业务单元的 `agent_presence`。

## 2. 核心口径

### 2.1 班表与时区

- 一个班表覆盖同一业务单元的一周，`week_start` 必须是周一。
- 班表保存 IANA 时区，默认 `Asia/Shanghai`；创建后不可修改。
- 班次使用本地时间；落班表时换算成带时区的 UTC `start_at/end_at`。
- `end_local < start_local` 表示跨天，结束日期顺延一天；两者相等返回 422，
  不用它表示 24 小时班。
- 周日的跨天班可以在下周一结束，仍属于该周班表。
- 不存在或有歧义的本地时间（例如 DST 跳变）返回 422，不静默猜测。

### 2.2 草稿、发布和修订

状态只允许：

```text
DRAFT -> PUBLISHED -> ARCHIVED
```

- 每个 `(business_unit_id, week_start)` 同时最多一个 DRAFT、一个 PUBLISHED。
- 发布草稿时，同事务把旧 PUBLISHED 置为 ARCHIVED，再发布新版本。
- PUBLISHED 与 ARCHIVED 的班表和条目不可修改。
- 修订必须从 PUBLISHED 或 ARCHIVED 克隆新 DRAFT；克隆条目保留源快照，
  因而源班次已停用时，克隆稿仍可直接发布。
- 草稿保存会按请求中的班次模板重新生成快照；发布后不再刷新。
- 重复发布同一 DRAFT 成功后的请求返回当前 PUBLISHED，不再次归档或写新版本。
- ARCHIVED 不可再次发布；空班表不可发布。

### 2.3 派班开关与兼容

- `enforce_published_schedule=false`：完全沿用现有在线/技能/风险/负载规则。
  新业务单元和未配置排班的旧业务单元均默认为 false，数据库无策略行时也按 false。
- `enforce_published_schedule=true`：候选坐席还必须在当前时刻有
  `PUBLISHED` 班表条目，满足 `start_at <= now < end_at`。
- 开启开关前必须已有覆盖当前周的 PUBLISHED 班表，否则返回 422
  `SCHEDULE_NOT_READY`，避免误开导致全部停派。
- 发布班表不自动打开开关；主管需显式开启。关闭开关立即恢复旧规则。
- 开关开启后，即使以后当前周没有班表，也不自动回退旧规则；坐席全部显示为
  未当班，队列保持待分配，页面给出缺口提示。
- 全局 Celery 派班按每个坐席所属业务单元分别判断，不能跨租户借用班表。
- 已有会话不因为下班被解绑；主管手工分配和人工接管不受此开关限制。

### 2.4 分配解释与并发

- 候选明细新增 `schedule_enforced`、`on_shift`、`shift_start_at/shift_end_at`；
  不当班时 `excluded_reasons` 增加“未在已发布班表当班”。
- 成功原因增加当班时间；原技能、风险和负载解释保留，响应只做增量扩展。
- 继续对会话使用行锁，避免同一会话被重复分配。
- 自动分配按固定顺序锁定相关 `AgentPresence` 行，并重算负载，避免两个并发
  分配事务把不同会话同时塞给同一坐席而超过 `max_conversations`。
- SQLite 测试验证逻辑，真实 PostgreSQL 测试验证行锁和唯一约束。

## 3. 数据模型

新增包 `apps/api/src/ticket_agent/scheduling/`。迁移的 `down_revision` 使用实现时
真实 head；规格编写时为 `c3e9b1d7a245`，实现前必须重新运行 `alembic heads`。

### 3.1 `agent_scheduling_policies`

| 列 | 类型 | 约束 |
| --- | --- | --- |
| `business_unit_id` | String(64) | PK |
| `enforce_published_schedule` | Boolean | NOT NULL，默认 false |
| `updated_by` | String(128) | NOT NULL |
| `created_at` / `updated_at` | DateTime(timezone=True) | NOT NULL |

### 3.2 `agent_shift_templates`

| 列 | 类型 | 约束 |
| --- | --- | --- |
| `id` | Uuid | PK |
| `business_unit_id` | String(64) | NOT NULL |
| `name` | String(100) | NOT NULL |
| `start_local` / `end_local` | Time | NOT NULL |
| `status` | String(16) | ACTIVE / ARCHIVED |
| `version` | Integer | NOT NULL，默认 1 |
| `created_by` | String(128) | NOT NULL |
| `created_at` / `updated_at` | DateTime(timezone=True) | NOT NULL |

约束：`UniqueConstraint(business_unit_id, name)`，索引业务单元与状态。
停用不物理删除；若仍被 DRAFT 条目引用则返回 409 `SHIFT_IN_USE`，
被已发布/已归档条目引用可正常停用。

### 3.3 `agent_rosters`

| 列 | 类型 | 约束 |
| --- | --- | --- |
| `id` | Uuid | PK |
| `business_unit_id` | String(64) | NOT NULL |
| `week_start` | Date | NOT NULL，周一 |
| `timezone` | String(64) | NOT NULL |
| `status` | String(16) | DRAFT / PUBLISHED / ARCHIVED |
| `version` | Integer | NOT NULL，草稿乐观锁，默认 1 |
| `cloned_from_roster_id` | Uuid | NULL，自引用 FK ON DELETE SET NULL |
| `created_by` / `published_by` | String(128) | created 非空，published 可空 |
| `published_at` | DateTime(timezone=True) | NULL |
| `created_at` / `updated_at` | DateTime(timezone=True) | NOT NULL |

约束与索引：

- 普通索引 `(business_unit_id, week_start)`。
- PostgreSQL/SQLite 部分唯一索引分别保证每业务单元每周最多一个 DRAFT、
  一个 PUBLISHED；ARCHIVED 数量不限。

### 3.4 `agent_roster_entries`

| 列 | 类型 | 约束 |
| --- | --- | --- |
| `id` | Uuid | PK |
| `roster_id` | Uuid | FK `agent_rosters.id` ON DELETE CASCADE |
| `shift_template_id` | Uuid | NULL，FK ON DELETE SET NULL |
| `agent_id` | String(128) | NOT NULL，逻辑身份，不新增 FK |
| `agent_display_name` | String(200) | NOT NULL，编排时快照 |
| `shift_date` | Date | NOT NULL，必须在该周内 |
| `start_at` / `end_at` | DateTime(timezone=True) | NOT NULL，end > start |
| `shift_name` | String(100) | NOT NULL，快照 |
| `shift_version` | Integer | NOT NULL，快照 |
| `snapshot_json` | JSON | NOT NULL |

约束：`UniqueConstraint(roster_id, agent_id, shift_date)`，首期同一坐席同一天
最多一个班次，从源头阻止重叠；索引 `(agent_id, start_at, end_at)` 和
`(roster_id, start_at, end_at)`。

`snapshot_json` 至少包含班次名称、版本、本地起止时间、班表时区、是否跨天。

## 4. 后端契约

### 4.1 文件

| 文件 | 内容 |
| --- | --- |
| `scheduling/models.py` | 上述四张表 |
| `scheduling/schemas.py` | 班次、班表、条目、策略、错误所需响应模型 |
| `scheduling/service.py` | 班次、班表、发布/克隆、当班查询与策略 |
| `scheduling/router.py` | HTTP 接口、权限与审计 |
| `customer_service/service.py` | 自动分配接入当班约束与并发保护 |
| `main.py` | 注册 scheduling router |

不新增 Celery 任务；现有 `ticket_agent.customer_service.auto_assign` 直接走新逻辑。

### 4.2 HTTP 接口

统一前缀 `/api/v1`，全部要求 `service.admin`，并走业务单元解析和检查。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET / POST | `/scheduling/shifts` | 班次列表 / 创建 |
| PATCH | `/scheduling/shifts/{shift_id}` | 改名、时间、停用；乐观锁 |
| GET / POST | `/scheduling/rosters` | 按周列出版本 / 获取或创建首个草稿 |
| GET | `/scheduling/rosters/{roster_id}` | 班表详情与条目 |
| PUT | `/scheduling/rosters/{roster_id}/draft` | 整体替换草稿条目，乐观锁 |
| POST | `/scheduling/rosters/{roster_id}/clone` | 从已发布/归档版本克隆草稿 |
| POST | `/scheduling/rosters/{roster_id}/publish` | 原子替换当前发布版本 |
| GET / PUT | `/scheduling/policy` | 查看 / 更新派班开关 |

草稿保存请求包含 `version` 和完整 `entries`。条目只提交
`agent_id`、`shift_template_id`、`shift_date`：

- 所有对象必须属于当前业务单元；坐席必须已存在于同业务单元 `agent_presence`。
- 同一坐席同日重复、日期越界、班次已停用、时间非法返回 422。
- 任一非法条目导致整个保存回滚，不允许只保存半张班表。
- 请求版本不一致且内容不同返回 409 `ROSTER_VERSION_CONFLICT`。
- 内容与当前条目完全相同时返回成功且不增加版本；即使这是前一次成功请求的
  重试，也不制造重复条目或伪冲突。
- 克隆若已有其他 DRAFT 返回 409，不生成多份草稿。

审计至少记录：`scheduling.shift.created/updated/archived`、
`scheduling.roster.created/draft_saved/cloned/published`、
`scheduling.policy.updated`，包含业务单元、资源 ID 和版本，不记录敏感信息。

### 4.3 主要错误

| HTTP | 错误码 | 场景 |
| --- | --- | --- |
| 403 | 既有权限错误 | agent 或无 `service.admin` 角色、跨租户访问 |
| 404 | `SHIFT_NOT_FOUND` / `ROSTER_NOT_FOUND` | 资源不存在 |
| 409 | `SHIFT_NAME_CONFLICT` | 同业务单元班次重名 |
| 409 | `SHIFT_IN_USE` | 停用仍被草稿引用的班次 |
| 409 | `ROSTER_DRAFT_EXISTS` | 重复克隆或已有草稿 |
| 409 | `ROSTER_VERSION_CONFLICT` | 乐观锁冲突 |
| 409 | `INVALID_ROSTER_STATE` | 修改发布稿、发布归档稿等 |
| 422 | `INVALID_SHIFT_TIME` / `INVALID_WEEK` | 时间、时区、周一校验失败 |
| 422 | `AGENT_NOT_FOUND` / `INVALID_ROSTER_ENTRY` | 坐席或条目非法 |
| 422 | `EMPTY_ROSTER` | 发布空班表 |
| 422 | `SCHEDULE_NOT_READY` | 无当前周发布稿却开启约束 |

## 5. 前端

新增 `/customer-service/scheduling`，归入客服运营菜单，要求 `service.admin`；
旧 `/customer-service/admin` 与 `/customer-service/workbench` 路由保持可用。

| 文件 | 改动 |
| --- | --- |
| `apps/web/src/SchedulingPage.tsx` | 新增主管排班页面 |
| `apps/web/src/App.tsx` | route meta、菜单、lazy import、路由渲染 |
| `apps/web/src/capabilities.ts` | 新路径映射到 `service.admin` |
| `apps/web/src/api.ts` / `types.ts` | 请求函数与类型 |

页面包含：

1. 周切换、时区显示、当前发布版本和草稿版本。
2. “按班表约束自动分配”开关，明确展示旧规则回退与无当班风险。
3. 班次模板表：新增、编辑、停用；显示跨天标识和版本。
4. 周班表网格：坐席为行、日期为列，从现有坐席目录选择坐席和班次。
5. 保存草稿、发布、从发布稿克隆修订按钮；发布前二次确认。
6. 当前当班坐席与未当班原因；无当前周发布稿时显示覆盖缺口。
7. 保存、发布、开关变更后自动刷新班表、当班状态和相关派班查询。

交互要求：

- 所有写按钮有 loading，请求期间禁用；成功/失败均显示明确反馈。
- 409 版本冲突提示重新加载，不静默覆盖他人修改。
- 重复点击不重复创建草稿、条目或发布版本。
- 首屏失败提供重试；空班表显示空态；表格窄屏横向滚动。

## 6. 验收矩阵

| # | 场景 | 期望 |
| --- | --- | --- |
| 1 | 正常主链路 | 建班次→建周草稿→排两人→发布→开启约束→自动分配，技能、风险、负载与当班均正确 |
| 2 | 旧规则兼容 | 无策略行或开关关闭时，无班表坐席仍按旧规则分配；旧自动分配测试不变 |
| 3 | 不当班拒绝 | 开关开启后，在线但无当前班次的坐席被排除，原因明确，会话仍在队列 |
| 4 | 边界时间 | `now=start_at` 可当班，`now=end_at` 不当班；跨天班覆盖次日 |
| 5 | 重复保存 | 相同草稿整体保存重试不重复条目、不增加版本 |
| 6 | 重复发布 | 同一草稿重复发布返回同一发布稿，不产生额外版本或重复审计 |
| 7 | 重复克隆/重名 | 并发或重复克隆最多一个草稿；班次重名被唯一约束拒绝 |
| 8 | 乐观锁 | 两个不同草稿保存基于同一版本，后者 409，不覆盖先保存内容 |
| 9 | 并发发布 | 真实 PostgreSQL 同时发布/克隆，最多一个 DRAFT 和一个 PUBLISHED，无 500 |
| 10 | 并发派班 | 真实 PostgreSQL 两个事务竞争同一会话只分配一次；多会话不超坐席容量 |
| 11 | 未授权 | agent 对所有排班读写和策略修改均 403；supervisor/admin 允许 |
| 12 | 跨租户 | 班次、坐席、班表、策略均不能跨业务单元引用或读取；全局 beat 不混用 |
| 13 | 非法状态 | 修改 PUBLISHED/ARCHIVED、发布 ARCHIVED、空班表发布均被拒绝 |
| 14 | 非法参数 | 非周一、相等起止时间、非法时区、周外日期、重复坐席日返回 422 |
| 15 | 失败恢复 | 多条草稿中一条非法则整体回滚；修正后重试成功；替换发布失败保留旧发布稿 |
| 16 | 模板快照 | 发布后修改/停用模板，历史条目时间与快照不变；新草稿保存才采用新模板 |
| 17 | 克隆就绪 | 从已发布稿克隆后条目、快照、跨天时间完整，源模板停用也能直接发布 |
| 18 | 开关恢复 | 开启后无当班会停派；关闭立即恢复旧规则；无当前周发布稿不能开启 |
| 19 | 不回收进行中会话 | 下班只阻止新分配，已分配会话和手工接管不受影响 |
| 20 | 迁移与旧数据 | 真实 PostgreSQL upgrade/downgrade、head、旧 presence/conversation 保留，默认策略 false |
| 21 | 前端入口与反馈 | 新路径直达 200，旧入口正常；按钮 loading/成功/失败/重复反馈和自动刷新完整 |
| 22 | 全对象链路 | 班次→草稿条目→发布快照→当班候选→会话分配→页面状态逐段核对 |

## 7. 验收命令与真实数据

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

真实服务验收使用临时业务单元 `bu_accept_scheduling`、两名临时人工坐席、
一个白班和一个跨天班、当前周班表，以及真实待分配会话/工单。逐段检查数据库、
API、Celery 调用和浏览器页面，结束后清理临时数据并确认残留为 0。

## 8. 外部依赖与风险

- 不新增外部服务；真实 PostgreSQL、Redis、Celery 和当前 compose 服务必须验收。
- 坐席目录依赖心跳后生成的 `agent_presence`，首次从未登录的人不能提前排班。
- `AgentPresence.agent_id` 当前全局唯一，跨业务单元身份模型本身的限制不在本期重构。
- 班表只约束自动分配，不等价于考勤，也不强制坐席上下线。
- 开启约束后，如果后续周未发布班表，自动分配会持续等待；页面必须显式提示。
- 不接入真实 HR/日历系统，此项标记为外部依赖未验收，而非生产考勤完成。

## 9. 待确认的推荐决策

1. 派班约束采用“显式开关，默认关闭”，发布班表后由主管再开启。
2. 首期只允许给已经产生过 presence 的人工坐席排班。
3. 下班不自动回收会话，只阻止新的自动分配。
