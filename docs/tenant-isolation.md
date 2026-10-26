# 多租户资源级隔离设计与回归验证

本文记录平台的多租户隔离方案、越权修复过程、复现方式和已知边界。目标不是
“把 `business_unit_id` 加进 WHERE 条件”，而是保证**任何一个按资源 ID 的读写、
任何一个默认列表或指标请求，都不会跨出租户边界**。

## 1. 威胁模型

- 租户标识：所有业务资源都带 `business_unit_id`。
- 身份来源：
  - 生产：OIDC JWT 的 `business_units` / `business_unit_id` 声明；
  - 开发：`X-Actor-Id`、`X-Actor-Role`、`X-Business-Unit-Id` 请求头。
- 不信任客户端传入的租户：请求头、query、body 里的租户值都必须与身份授权的
  `business_units` 集合比对。
- 主要攻击面：
  1. 按 ID 读取或写入：`GET /tickets/{id}`、`PATCH /knowledge-documents/{id}`、
     会话接管、电商素材上传等；
  2. 不传租户参数的列表和指标：可能回落成硬编码的 `bu_demo` 或“不过滤”；
  3. SSE / 文件下载 / 上传等非 JSON 路径；
  4. 全局唯一的业务键，例如工单 `Idempotency-Key`；
  5. 批量接口：任一元素越权时不能让批次部分提交。

## 2. 三层防线

### 2.1 中间件：只覆盖“显式声明”的租户

`src/ticket_agent/main.py` 中的两个守卫：

- `tenant_query_guard`：检查 URL 中显式出现的 `?business_unit_id=`；
- `tenant_body_guard`：检查 POST/PUT/PATCH 顶层 JSON 的 `business_unit_id`。

它们的职责是“客户端声明外部租户时直接拒绝”，**不负责资源归属**。因此不能把
中间件当成完整隔离方案——这正是本次修复的起点。

### 2.2 路由层：资源归属校验

`src/ticket_agent/identity/dependencies.py` 提供两个原语：

```python
ensure_business_unit_access(principal, resource.business_unit_id)
resolve_business_unit(principal, requested)  # requested 为空时回落 primary BU
```

统一约定：

| 场景 | 结果 |
| --- | --- |
| 资源属于其他租户 | `403 BUSINESS_UNIT_ACCESS_DENIED` |
| 显式请求其他租户的 query/body | `403 BUSINESS_UNIT_ACCESS_DENIED` |
| 身份没有任何授权租户 | `403 BUSINESS_UNIT_CONTEXT_REQUIRED` |
| 列表/指标未传租户 | 回落 `principal.primary_business_unit_id` |

路由层先 `service.get(id)` 拿到资源，再校验归属，最后才执行写操作。检查必须发生在
任何副作用之前：SSE 在返回 `StreamingResponse` 之前校验；素材上传在
`await request.body()` 之前校验；批次接口在执行前做 preflight。

### 2.3 服务层：关键写路径兜底

对状态机写操作，校验下沉到 service，避免新增路由时忘记加 guard：

- `TicketService._locked_ticket(..., principal=...)`：takeover、review、分类覆盖、
  同步重试、归档都先校验工单归属，再修改状态并 commit；
- `TicketService.create`：幂等键命中已存在工单时先校验归属，再判断是否重放；
- `AgentRunService.trace(run_id, principal=...)`：Trace 只对同租户审计角色可见。

## 3. 覆盖范围

| 模块 | 按 ID 路由 | 列表 / 指标 |
| --- | --- | --- |
| 工单 | detail、takeover、review、分类覆盖、同步重试、归档 | 默认列表、批量重试、测试数据清理 |
| 知识 | 文档、版本、发布、上传、修复任务、评测用例/运行 | 文档、反馈、聚类、修复任务、评测、RAG 指标 |
| 客服会话 | 详情、SSE、消息、接管、释放、人工回复、建议、优化、改派、归档 | 会话、通知、指标、历史指标 |
| 电商 | 品类、商品、素材、上架任务、视频任务、批次任务、审核、重试 | 商品、品类、素材、任务、视频任务、指标、导入预览 |
| 可观测 | AgentRun Trace | agent-runs、tool-calls、models/tools/sync/rag 指标、budget |
| 平台配置 | 员工、草案、模板、Skill、MCP、业务入口、主管任务 | 各列表默认回落 primary BU |

`/metrics`（Prometheus 抓取端点）保持全局聚合，因为它是 token 保护的基础设施
端点，不面向租户用户。

## 4. 关键修复案例

### 4.1 Idempotency-Key 跨租户泄露

工单幂等键是全局唯一索引。修复前，beta 租户复用 alpha 的 `Idempotency-Key`
会得到 `409 IDEMPOTENCY_CONFLICT`，响应上下文里带出 alpha 的 `ticket_id`。
这是典型的“业务键泄露资源存在性”。

修复方式：在重放逻辑之前先查询已存在工单并校验归属：

```python
existing = self.session.scalar(
    select(Ticket).where(Ticket.idempotency_key == idempotency_key)
)
if existing is not None:
    ensure_business_unit_access(principal, existing.business_unit_id)
    return self._validate_replay(existing, request_hash), False, None
```

### 4.2 非 JSON 路径

- SSE：先同步校验会话归属，再返回流式响应；
- 素材上传：先校验商品归属，再读取请求体；
- CSV 导入预览：除 query 租户外，还校验 `category_profile_id` 指向的品类档案；
- 批量创建上架任务：对每个商品 ID 先 preflight，任一越权则整批 403，不新增任务。

### 4.3 默认租户

列表接口原来把 query 默认值写成 `"bu_demo"`，非演示租户即使不传参数也会被判定为
越权。现已统一改为 `None` + `resolve_business_unit`，缺省回落到当前身份的主业务单元。

创建接口的 body `business_unit_id` 仍保留 `bu_demo` 默认值：省略字段时按该租户处理，
非该租户会得到 403。前端在请求层把 `bu_demo` 占位符替换为当前激活租户。

## 5. 攻击复现

启动开发环境后，用两个租户的请求头复现：

```bash
ALPHA_TICKET_ID=<alpha 工单 ID>

# beta 读取 alpha 工单：403，而不是 200
curl -i -H 'X-Actor-Id: beta-agent' \
  -H 'X-Actor-Role: agent' \
  -H 'X-Business-Unit-Id: bu_beta' \
  "http://127.0.0.1:8000/api/v1/tickets/${ALPHA_TICKET_ID}"

# beta 不传租户的默认列表：只包含 bu_beta
curl -s -H 'X-Actor-Id: beta-agent' \
  -H 'X-Actor-Role: agent' \
  -H 'X-Business-Unit-Id: bu_beta' \
  "http://127.0.0.1:8000/api/v1/tickets" \
  | jq -r '.items[].business_unit_id' | sort -u

# beta 显式请求 alpha：403
curl -i -H 'X-Actor-Id: beta-agent' \
  -H 'X-Actor-Role: agent' \
  -H 'X-Business-Unit-Id: bu_beta' \
  "http://127.0.0.1:8000/api/v1/tickets?business_unit_id=bu_alpha"
```

写操作同样应返回 403，且原工单 `version/status` 不变；回归测试会用 ORM 直接复查
数据库，确认没有状态变更或额外 OutboxEvent。

## 6. 回归测试

`apps/api/tests/integration/test_tenant_resource_access.py` 包含 6 个测试：

1. 工单跨租户读写、批量重试、测试数据清理、幂等键复用；
2. 知识文档/版本/上传/发布/评测资源；
3. 客服会话、SSE、消息、接管、建议/优化、改派；
4. 电商商品、素材、上架任务、导入预览、批量任务；
5. AgentRun/ToolCall/各指标接口的租户收敛；
6. 列表缺省租户回落到自身业务单元。

```bash
cd apps/api
uv run pytest tests/integration/test_tenant_resource_access.py -v
```

全量回归与覆盖率：

```bash
uv run pytest --cov=src/ticket_agent --cov-report=term
uv run ruff check src tests
uv run mypy src
```

## 7. 已知边界与取舍

- **403 vs 404**：越权统一返回 403，沿用项目既有约定，便于前端区分“无权限”和
  “不存在”。代价是泄露资源存在性；若要隐藏存在性，可改为 404，但需要同步调整
  前端错误提示和测试。
- **服务层默认过滤**：目前是路由/服务显式校验。长期可引入 SQLAlchemy
  `with_loader_criteria` 或请求级租户上下文，把过滤下沉到数据层；迁移成本较高，
  本次未做。
- **异步任务**：Celery worker 和 Outbox 没有 HTTP 身份上下文，内部按任务自带的
  租户字段处理，不经过 `Principal`；HTTP 入口负责在入队前完成归属校验。
- **Prometheus `/metrics`**：保持全局聚合，不按租户拆分。
