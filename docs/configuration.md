# 模型与外部集成配置

## 配置注入方式

密钥与开关统一写进仓库根目录 `.env`（已在 `.gitignore` 中）：

- `Makefile` 与 `scripts/*.sh` 会设置 `COMPOSE_ENV_FILES=<repo>/.env`，因此 compose
  的 `${VAR:-default}` 插值读到的就是根 `.env`。此前 compose 只读项目目录
  `infra/compose/.env`，根 `.env` 里的密钥会在容器里变成空串。
  `COMPOSE_ENV_FILES` 会**替换**默认的 `.env` 查找，所以请统一只维护根 `.env`；
  `infra/compose/.env` 即使存在也不再参与插值。
- 服务同时通过 `env_file: ../../.env` 注入整份 `.env`；`environment` 中的同名变量
  优先级更高，所以不要把密钥再写进 compose 文件。
- 主模型只读 `MODEL_BASE_URL / MODEL_API_KEY / MODEL_NAME`。compose 不再把
  `ECOMMERCE_CONTENT_*` 映射成 `MODEL_*`，避免电商文案密钥在不被察觉时变成主模型密钥。

## 千问配置

将密钥只写入本机 `.env`：

```text
ECOMMERCE_CONTENT_PROVIDER=openai_compatible
ECOMMERCE_CONTENT_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
ECOMMERCE_CONTENT_MODEL_NAME=qwen-plus
ECOMMERCE_CONTENT_API_KEY=<local-secret>
ECOMMERCE_CONTENT_FALLBACK_TO_LOCAL=true
ECOMMERCE_IMAGE_PROVIDER=dashscope
ECOMMERCE_IMAGE_BASE_URL=https://dashscope.aliyuncs.com
ECOMMERCE_IMAGE_MODEL_NAME=z-image-turbo
ECOMMERCE_IMAGE_FALLBACK_TO_LOCAL=true
ECOMMERCE_VISUAL_AUDIT_PROVIDER=dashscope_ocr
ECOMMERCE_VISUAL_AUDIT_MODEL_NAME=qwen-vl-ocr
ECOMMERCE_TTS_PROVIDER=dashscope_qwen
ECOMMERCE_TTS_MODEL_NAME=qwen3-tts-flash
ECOMMERCE_TTS_VOICE=Cherry
```

未配置密钥时继续使用本地模板，页面和素材元数据会标明实际 Provider。

## 演示数据恢复

“运行与审计”中的恢复操作只对 `bu_demo` 生效，并要求管理员身份、演示/测试环境
以及显式确认请求头 `X-Demo-Reset-Confirm: reset-bu_demo`。接口先返回 `202` 和
`job_id`，恢复脚本在后台执行；前端轮询 `GET /api/v1/demo/reset/{job_id}` 直到
`SUCCEEDED` 或 `FAILED`。

```text
DEMO_RESET_ENABLED=true
DEMO_RESET_BASE_URL=http://127.0.0.1:8000
```

`DEMO_RESET_BASE_URL` 是后台任务调用种子脚本时使用的 API 地址，默认取 Compose
栈内的本地端口。生产环境即使误设 `DEMO_RESET_ENABLED=true`，也会因为
`APP_ENV` 非 `development`/`test` 而拒绝执行。

## 物流状态查询

物流状态必须来自订单或物流系统，不能由大模型推断。配置企业 OMS、WMS
或快递查询服务的 HTTP JSON 接口：

```text
LOGISTICS_QUERY_PROVIDER=http_json
LOGISTICS_QUERY_BASE_URL=https://your-logistics-service.example/query
LOGISTICS_QUERY_API_KEY=<local-secret>
LOGISTICS_QUERY_TIMEOUT_SECONDS=20
```

系统向该地址发送：

```json
{
  "order_id": "DEMO-ORDER-001",
  "tracking_number": "SF1234567890",
  "carrier_code": "SF"
}
```

接口应返回统一物流结构：

```json
{
  "order_id": "DEMO-ORDER-001",
  "tracking_number": "SF1234567890",
  "carrier_code": "SF",
  "status": "IN_TRANSIT",
  "status_label": "运输中",
  "latest_event_at": "2026-10-24T12:00:00Z",
  "events": [
    {
      "occurred_at": "2026-10-24T12:00:00Z",
      "location": "杭州转运中心",
      "description": "快件已到达转运中心"
    }
  ]
}
```

`order_id` 和 `tracking_number` 至少提供一个。未配置真实接口时，客服页面会明确
显示“物流查询接口尚未配置”，不会生成虚假物流状态。

## 请求限流

模型、工具和图片/视频生成等昂贵接口按“身份 + 业务单元”做窗口限流，默认每 60 秒
120 次；超限返回 `429 RATE_LIMITED` 并带 `Retry-After`。

- Compose 和 .env.example 默认启用 Redis 固定窗口，多进程共享计数；
- Redis 不可用时降级为进程内滑动窗口，避免限流组件故障导致业务接口整体不可用；
- 测试与本地单进程开发默认关闭，可用 `RATE_LIMIT_ENABLED` 和
  `RATE_LIMIT_BACKEND=redis` 开启；
- 覆盖客服消息、回复建议与优化、知识检索与评测、电商图片/分镜/视频生成、
  MCP 审批执行；
- 不同租户分别计数，一个租户不会占用另一个租户的额度；
- 被拒绝的请求计入 Prometheus 计数器
  `ticket_worker_rate_limit_rejections_total`；该计数器是进程内累计值，多副本部署时
  由 Prometheus 对各副本求和。`infra/prometheus/alerts.yml` 中的
  `TicketRateLimitRejectionsHigh` 会在持续超限时告警。

```bash
cd apps/api
uv run pytest tests/unit/test_rate_limit.py tests/integration/test_rate_limiting.py -v
```

## 请求体大小限制

`MAX_REQUEST_BYTES`（默认 32 MiB）限制 `POST`、`PUT`、`PATCH` 请求体。中间件同时
检查 `Content-Length` 和实际读取的字节数，因此没有长度头的分块上传也会在超限时
立即中止，不会先把整个请求体读入内存。

超限返回 `413 PAYLOAD_TOO_LARGE`，响应仍带 CORS 和 correlation ID 头，前端可以按
统一错误结构展示。上传大文件或调整客户资料前，需要同时调整反向代理和
`MAX_REQUEST_BYTES`。

```bash
cd apps/api
uv run pytest tests/integration/test_request_body_limit.py -v
```

## 会话轮次租约与卡死回收

每轮买家消息是一个运行时事务单元（`conversation_turns`），状态只能沿
`PENDING → RUNNING → COMPLETED / NEEDS_HUMAN / FAILED_RETRYABLE /
FAILED_TERMINAL / CANCELLED` 的合法边迁移，每次迁移写入
`conversation_turn_events`。

- `CONVERSATION_TURN_LEASE_SECONDS`（默认 120）：worker 认领轮次时持有的租约；
  租约过期视为 worker 已崩溃。
- `CONVERSATION_TURN_MAX_ATTEMPTS`（默认 3）：超过后轮次进入 `FAILED_TERMINAL`，
  避免定时任务在毒轮次上反复重试。
- `CONVERSATION_TURN_RECLAIM_BATCH_SIZE`（默认 20）：每次回收批大小。

Celery Beat 每 30 秒执行 `ticket_agent.customer_service.reclaim_turns`：过期
`RUNNING` 轮次回到 `PENDING` 并重新派发，超过上限的轮次标记终态。运维也可手动
触发 `POST /api/v1/customer-service/turns/reclaim`（需要 `operations.manage`）。

业务层面的拒绝（无知识、未配置技能、缺少工单上下文）直接进入
`FAILED_TERMINAL`；只有显式标记 `retryable` 的问题和未预期异常才重试。

```bash
cd apps/api
uv run pytest tests/integration/test_conversation_turn_events.py -v
```

## 上下文装配、会话记忆与员工交接

每轮实际使用的上下文由 `customer_service/context.py` 统一装配，顺序固定：
会话记忆 → 最近一次交接摘要 → 消息窗口 → 当前消息，结果写入
`conversation_turns.context_json` 并附在 `CONTEXT_ASSEMBLED` 事件里。

- 消息窗口默认 `4000` 字符、最多 `20` 条（`DEFAULT_HISTORY_BUDGET_CHARS` /
  `DEFAULT_HISTORY_MAX_MESSAGES`，当前是代码常量，不通过环境变量调整），且只取
  `sequence` 小于当前消息的条目，排队期间后发的消息不会混进上一轮。
- 会话记忆读取时自动把 v1 行升级为 v2 并回写；v2 的 `facts` 带 `source_turn_id`。
- 同一会话的轮次串行执行，后到的轮次保持 `PENDING` 并持有有效租约，避免被回收器
  误判为卡死；完成方结束时会接力派发下一轮（单次最多 10 轮）。首条消息建单使用
  `TicketService.create(commit=False)`，会话行锁不会被内部提交打断；若仍与并发
  建单相遇，按 `CONV-<会话>-initial` 复用同一张工单。
- 客户端可传 `client_message_id` 做幂等重放；邮件连接器用收件行 id 派生该值。
- 会话详情里的每条消息带 `turn_id`（迁移前的旧消息为 `null`）。
- 员工交接写入 `conversation_handoffs`；主管切换员工调用
  `POST /api/v1/customer-service/conversations/{conversation_id}/employee`
  （需要 `operations.manage`），重复切换到同一位员工返回 409
  `EMPLOYEE_UNCHANGED`，跨业务单元的员工返回 400
  `HANDOFF_EMPLOYEE_UNIT_MISMATCH`，跨领域（如同一单元的 HR 员工）返回 409
  `EMPLOYEE_DOMAIN_MISMATCH`。

```bash
cd apps/api
uv run pytest tests/integration/test_conversation_context_handoff.py -v
uv run python scripts/acceptance_conversation_runtime.py http://127.0.0.1:8000
```

## 知识库嵌入与重建索引

```text
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_BASE_URL=https://embedding.example/v1
EMBEDDING_MODEL_NAME=BAAI/bge-m3
EMBEDDING_API_KEY=<local-secret>
EMBEDDING_DIMENSIONS=1024
# 端点支持 OpenAI dimensions 参数时开启；DashScope text-embedding-v3 需要。
EMBEDDING_SEND_DIMENSIONS=true
EMBEDDING_FALLBACK_TO_LOCAL=false
# 自托管无鉴权端点（如 TEI）设为 true；否则缺少 API Key 会被当作未配置。
EMBEDDING_ALLOW_EMPTY_API_KEY=false
KNOWLEDGE_CHUNKING_VERSION=v2
KNOWLEDGE_CHUNK_TARGET_CHARS=800
KNOWLEDGE_CHUNK_MAX_CHARS=1200
KNOWLEDGE_CONTEXT_PRUNE_ENABLED=true
KNOWLEDGE_CONTEXT_MAX_CHARS=5000
```

- **推荐默认**是语义嵌入：`.env.example` 与 compose 默认指向 DashScope
  `text-embedding-v3`（`EMBEDDING_DIMENSIONS=256`、`EMBEDDING_SEND_DIMENSIONS=true`）。
  没填 `EMBEDDING_API_KEY` 时启动日志会提示，并直接走本地 `local-hash-256`
  演示模式，不会每次请求都去撞远端失败；此时 `/metrics/rag` 返回
  `embedding_quality=demo`，运营页显示橙色提示。填入密钥后必须重建索引。
- 公开评测集上，本地哈希 HOLDOUT chunk/document recall 为 0.76/0.663，
  `text-embedding-v3` 为 0.96/0.8557；这是公开人社问答语料的结果，不是内部
  工单，不能直接外推为生产质量。
- `EMBEDDING_DIMENSIONS` 必须与模型真实维度一致，响应维度不符时请求失败。
- `EMBEDDING_SEND_DIMENSIONS=true` 时请求体带 `"dimensions"`。部分服务默认
  返回 1024 维，只有显式传参才能得到 256 维；不支持该参数的端点保持默认
  `false`，避免被服务端拒绝。
- `EMBEDDING_FALLBACK_TO_LOCAL=false` 时远端失败直接报错，版本不落库；
  设为 `true` 时按真实使用的本地模型名写入，并在 chunk 元数据标
  `embedding_fallback_used=true`，避免把本地向量记成远端模型。
- 切换模型或分块版本后，调用管理员接口重建：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/knowledge/reindex \
  -H "X-Actor-Id: admin-1" -H "X-Actor-Role: admin" \
  -H "Content-Type: application/json" \
  -d '{"business_unit_id": "bu_demo", "chunking_version": "v2"}'
```

`GET /api/v1/knowledge/reindex-jobs` 查询任务状态；`/api/v1/metrics/rag` 的
`reindex_pending_versions` 表示仍是旧模型、尚未重建的版本数，
`stale_evaluation_chunk_refs` 表示评测用例仍指向已删除 chunk 的引用数。

更稳妥的做法是给评测用例配置段落级期望：

```json
"expected_passages": [
  {"document_id": "<knowledge document id>", "text": "签收后七天内可以申请退款"}
]
```

评测运行时按当前生效版本的 chunk 文本解析 chunk，重建索引或切换分块版本都
不需要改用例；段落存在时优先于 `expected_chunk_ids`。段落文本找不到时用例
直接失败并返回 `unresolved_passages`，整次运行 verdict 为 FAIL
（`scripts/evaluate_rag.py --max-unresolved-passages` 默认 0）。

没有段落的旧用例仍走 chunk 引用重映射（完全一致 → 合并 → 拆分，见
`docs/features.md`）。HOLDOUT 用例只接受“文本完全一致”的换主键，合并/拆分
改动会保留原值并计入 stale。无法匹配的引用保持原样并计入
`stale_evaluation_chunk_refs`；此时应先核对用例再跑评测，不要依赖
`--min-chunk-recall-at-k` 的失败去反向推理。带段落的用例不参与重映射，也不
计入 stale。

- 迁移顺序：先 `alembic upgrade head` 再启动应用。开发模式启动会执行
  `init_db()` 建表，顺序颠倒会出现 `DuplicateTable`。

## 混合检索（BM25 词面通道 + RRF）

```text
KNOWLEDGE_RETRIEVAL_MODE=dense   # dense | hybrid
KNOWLEDGE_RRF_K=60
```

- `dense`（默认）只走向量召回；`hybrid` 在 PostgreSQL 上额外执行
  `to_tsvector('simple', lexical_text)` 全文召回，两路结果用 RRF 融合后再
  交给 HybridReranker。
- 词面通道依赖 `knowledge_chunks.lexical_text` 与表达式 GIN 索引
  `ix_knowledge_chunks_lexical`（迁移 `d5e1f8c2b903`）。SQLite 环境没有全文
  检索，会自动降级为 `dense`，`/knowledge/search` 的 `retrieval_mode` 返回
  实际生效的模式。
- 升级到本版本后历史 chunk 的 `lexical_text` 为空，迁移**不会**自动回填；
  `/api/v1/metrics/rag` 的 `reindex_pending_versions` 会把它们计入待重建，
  先执行一次重建再切换 `hybrid`：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/knowledge/reindex \
  -H "X-Actor-Id: admin-1" -H "X-Actor-Role: admin" \
  -H "Content-Type: application/json" \
  -d '{"business_unit_id": "bu_demo"}'
```

- 分词规则在 `apps/api/src/ticket_agent/knowledge/tokenizer.py`：中文按单字 +
  二元组，英文/数字保留整词，tsquery 侧按标点拆分（避免 PostgreSQL 把
  `hx-9080b` 解析成相邻短语）。改动该文件需递增 `LEXICAL_TOKENIZER_VERSION`，
  否则重建任务会判定 chunk 仍然是最新的。

## 远端重排（cross-encoder）

```text
KNOWLEDGE_RERANK_PROVIDER=external
RERANK_BASE_URL=https://rerank.example/v1
RERANK_MODEL_NAME=BAAI/bge-reranker-v2-m3
RERANK_API_KEY=<local-secret>
RERANK_TIMEOUT_SECONDS=3
RERANK_FALLBACK_TO_LOCAL=true
KNOWLEDGE_RERANK_MIN_CANDIDATES=1
KNOWLEDGE_RERANK_TRIGGER_SCORE=0
KNOWLEDGE_RERANK_MAX_CANDIDATES=30
```

- 契约固定为 `POST {RERANK_BASE_URL}/rerank`，请求体
  `{model, query, documents[], top_n}`，响应 `[{index, relevance_score}]`，
  分数须在 `[0, 1]`；自托管可用 TEI / Infinity 承载 `bge-reranker-v2-m3`。
- 触发条件：候选数 ≥ `KNOWLEDGE_RERANK_MIN_CANDIDATES`，或最高向量分低于
  `KNOWLEDGE_RERANK_TRIGGER_SCORE`。默认值（1 / 0）表示只要有候选就调用远端，
  与旧行为一致；想省成本可把 `MIN_CANDIDATES` 调大、`TRIGGER_SCORE` 设为
  0.4–0.5。
- 单次最多发送 `KNOWLEDGE_RERANK_MAX_CANDIDATES` 条（默认 30）控制延迟；
  `top_n` 取 `min(top_k, 候选数)`。
- 远端超时/5xx/响应非法时，`RERANK_FALLBACK_TO_LOCAL=true` 回退本地重排并
  计入 Prometheus 计数器 `ticket_worker_rag_rerank_fallbacks_total`；设为
  `false` 则检索返回 `503 RERANK_UNAVAILABLE`（可重试），不返回未重排结果。
  默认回退，因此检索不会因重排失败而整体失败。
- DashScope 原生 rerank：

```text
KNOWLEDGE_RERANK_PROVIDER=dashscope
RERANK_MODEL_NAME=gte-rerank-v2
# 留空时继承 MODEL_API_KEY
RERANK_API_KEY=<local-secret>
```

  该模式固定请求
  `https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank`
  （`RERANK_BASE_URL` 可覆盖），body 为
  `{model, input:{query, documents}, parameters:{return_documents:false, top_n}}`，
  解析 `output.results`。公开评测集上全量重排提升了调参集但降低了留出集，
  因此默认仍为 `local`；生产启用前需在内部工单留出集重新评估。
- 数字员工档案里配置的 rerank 端点会覆盖全局设置，并额外记录
  `usage_guard` 的 token 与耗时。
- compose 栈通过 `.env` 透传上述变量（默认 `local`），`RERANK_API_KEY` 默认为空，
  密钥只在运行时从本机 `.env` 注入，不写入镜像或 compose 文件。

## 查询改写（多轮消解 + LLM 多查询）

```text
KNOWLEDGE_QUERY_CONTEXT_ENABLED=true
KNOWLEDGE_QUERY_CONTEXT_HISTORY_TURNS=3
KNOWLEDGE_QUERY_REWRITE_ENABLED=false
KNOWLEDGE_QUERY_REWRITE_VARIANTS=2
KNOWLEDGE_QUERY_REWRITE_TRIGGER_SCORE=0.3
KNOWLEDGE_QUERY_REWRITE_TIMEOUT_SECONDS=2
QUERY_REWRITE_BASE_URL=
QUERY_REWRITE_API_KEY=
QUERY_REWRITE_MODEL_NAME=
```

- `KNOWLEDGE_QUERY_CONTEXT_ENABLED`（默认开，无模型）：客服会话中只把**当前买家
  问题**作为查询，最近 `KNOWLEDGE_QUERY_CONTEXT_HISTORY_TURNS` 轮买家消息作为
  上下文。查询含“它/这个/那个/那/该”等指代时，优先替换为历史中的型号、订单号
  （如 `HX-9080B`）；没有可替换实体时把上一轮问题拼到前面。原始问题仍作为
  第二路召回参与 RRF，消解错误不会让原本命中的结果掉出。
- `KNOWLEDGE_QUERY_REWRITE_ENABLED`（默认关）：开启后仅在最高分低于
  `KNOWLEDGE_QUERY_REWRITE_TRIGGER_SCORE` 时调用 OpenAI 兼容
  `POST {QUERY_REWRITE_BASE_URL}/chat/completions` 生成
  `KNOWLEDGE_QUERY_REWRITE_VARIANTS` 条替代查询，与原始候选再 RRF 融合。
- `QUERY_REWRITE_*` 为空且 `MODEL_PROVIDER=openai_compatible` 时自动继承
  `MODEL_BASE_URL` / `MODEL_API_KEY` / `MODEL_NAME`；密钥同样只从本机 `.env`
  注入。总超时为 `KNOWLEDGE_QUERY_REWRITE_TIMEOUT_SECONDS`（默认 2s）。
- 远端超时、5xx、空结果或非法响应时静默保留本地排序并计数
  `ticket_worker_rag_query_rewrite_fallbacks_total`；成功扩展计入
  `ticket_worker_rag_query_rewrites_total`。检索不会因改写失败而失败。
- 关闭两个开关后，检索行为与升级前完全一致：单查询、单次嵌入，不读取历史。

## 外部连接（邮件 / 只读 HTTP JSON）

连接器密钥不写入数据库、镜像或日志。连接器记录只保存 `secret_ref`（环境变量名），
运行时按以下顺序解析：

1. 进程环境变量（compose 从根 `.env` 注入）。
2. `CONNECTOR_SECRETS_JSON`，格式为 `{"SUPPORT_MAIL_PASSWORD": "..."}`。

```text
CONNECTOR_SECRETS_JSON=
CONNECTOR_POLL_BATCH_SIZE=20
CONNECTOR_AUTO_REPLY_ENABLED=true
CONNECTOR_MAX_INBOUND_ATTEMPTS=3
SUPPORT_MAIL_PASSWORD=
```

- `CONNECTOR_AUTO_REPLY_ENABLED` 是全局总开关；单连接器还需
  `auto_reply_enabled=true`，并且数字员工回答完成、关联工单完成才会自动回信。
- `CONNECTOR_MAX_INBOUND_ATTEMPTS` 控制入站消息失败后的最大尝试次数，超过后保留
  `FAILED` 记录，等待人工重试。
- 邮件连接器配置示例（数据库 `config_json`，页面等价字段）：

```json
{
  "imap_host": "imap.example.com",
  "imap_port": 993,
  "imap_ssl": true,
  "imap_folder": "INBOX",
  "smtp_host": "smtp.example.com",
  "smtp_port": 465,
  "smtp_ssl": true,
  "from_address": "support@example.com",
  "username": "support@example.com"
}
```

- 本地验收可使用 `mock-mail`（GreenMail，仅 `test` profile）：

```text
docker compose -f infra/compose/docker-compose.yml --profile test up -d mock-mail
```

  GreenMail 暴露 SMTP `3025` 与 IMAP `3143`，关闭认证；连接器配置需设置
  `imap_ssl=false`、`smtp_ssl=false`，且 `from_address` 使用 GreenMail 已创建的
  测试邮箱。
- 只读 HTTP JSON 连接器配置示例：

```json
{
  "base_url": "https://orders.example.com",
  "path": "/api/orders/O-1001",
  "health_path": "/health",
  "timeout_seconds": 20
}
```

  配置 `secret_ref` 时，请求会附加 `Authorization: Bearer <secret>`；可通过
  `auth_header` / `auth_scheme` 覆盖。该连接器仅允许 GET，写操作继续使用 MCP 审批。
