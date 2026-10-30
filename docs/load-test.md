# 只读并发压测基线与复现

这是一组本地演示环境的只读压测基线，用于回答“接口在并发下会不会报错、延迟如何
变化”，不用于证明生产容量，也不能替代真实业务场景和外部依赖的压测。

## 压测范围

- 只调用列表和指标类只读接口，不创建工单、不触发模型、不写入审批或会话。
- 不测模型生成、知识检索、MCP 工具和写操作；这些路径依赖外部服务和人工流程，
  需要单独的故障注入与容量测试。
- 被测的四个接口没有配置昂贵接口限流，因此结果中没有 `429` 是预期行为。

## 环境

| 项目 | 配置 |
|---|---|
| 主机 | Apple M5，16 GiB 内存，macOS |
| Docker | Docker Compose 5.3.1，10 个 CPU、约 7.8 GiB 内存 |
| API | `ticket-agent-api:local`，单 uvicorn worker，`APP_AUTH_MODE=dev` |
| 数据库 | PostgreSQL 容器，连接池 20 + 20 overflow |
| 缓存/任务 | Redis 容器，Celery worker 和 beat 同时运行 |
| 模型 | 演示配置；本次只读接口不调用模型 |
| 数据 | 本地演示数据（工单、会话、员工和知识都已写入） |
| 压测客户端 | 与 API 同机运行，保持 HTTP keep-alive |

## 被测接口

| 接口 | 说明 |
|---|---|
| `GET /api/v1/tickets?limit=50` | 工单列表，含默认业务单元过滤 |
| `GET /api/v1/customer-service/conversations` | 客服会话列表 |
| `GET /api/v1/digital-employees` | 数字员工列表及配置视图 |
| `GET /api/v1/customer-service/metrics` | 客服指标聚合 |

请求统一携带开发身份头：

```text
X-Actor-Id: loadtest-monitor
X-Actor-Role: admin
X-Business-Unit-Id: bu_demo
```

## 方法

[`scripts/load_test.py`](../scripts/load_test.py) 先对四个接口各发一次预热请求，
确认返回 2xx 后，按 `concurrency` 启动固定数量的异步 worker，在 `duration` 秒内
持续轮询四个接口。延迟按请求完成时间统计，百分位使用最近秩（nearest rank），
RPS 按实际计时窗口计算。

```bash
# 仓库根目录，API 已启动
uv run --project apps/api python scripts/load_test.py \
  --concurrency 50 --duration 60 --json /tmp/load-test-50.json

# 或使用 Make 目标，额外参数通过 LOAD_TEST_ARGS 传入
make load-test LOAD_TEST_CONCURRENCY=100 LOAD_TEST_DURATION=60
```

单接口复测时使用 `--path` 覆盖默认接口，例如：

```bash
uv run --project apps/api python scripts/load_test.py \
  --concurrency 50 --duration 30 \
  --path '/api/v1/tickets?limit=50'
```

默认允许 1% 错误率；超过阈值时脚本以退出码 1 结束，便于接入 CI 或验收脚本。

## 结果

2026-10-26 本地连续运行结果：

| 并发 | 时长 | 请求数 | 成功率 | 吞吐 RPS | P50 | P95 | P99 | 最大 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 | 5s | 1,351 | 100% | 269.52 | 17.30 ms | 30.48 ms | 48.82 ms | 124.52 ms |
| 50 | 60s | 10,347 | 100% | 171.83 | 282.38 ms | 460.89 ms | 548.33 ms | 697.21 ms |
| 100（第一次） | 60s | 10,396 | 99.99% | 171.68 | 569.05 ms | 854.84 ms | 993.38 ms | 1,246.81 ms |
| 100（第二次） | 60s | 10,361 | 100% | 171.72 | 567.98 ms | 850.71 ms | 985.42 ms | 1,535.60 ms |

所有失败请求只有一个，出现在第一次 100 并发运行的 502；第二次 100 并发没有复现。
该 502 没有出现在 uvicorn 访问日志中，因此更像来自 Docker 端口转发或连接排队，
而不是业务异常；这一点需要在独立压测机上用更长运行时间继续确认。

单接口复测（50 并发，各 15 秒，按顺序执行）：

| 接口 | 请求数 | 成功率 | 吞吐 RPS | P50 | P95 | P99 |
|---|---:|---:|---:|---:|---:|---:|
| 工单列表 | 4,167 | 100% | 275.11 | 174.82 ms | 275.35 ms | 321.75 ms |
| 客服会话列表 | 2,240 | 100% | 147.54 | 332.79 ms | 495.38 ms | 645.07 ms |
| 数字员工列表 | 2,509 | 100% | 164.71 | 289.25 ms | 495.80 ms | 562.49 ms |
| 客服指标 | 2,085 | 100% | 136.88 | 359.60 ms | 517.48 ms | 674.31 ms |

单接口吞吐相加明显高于混合压测，是因为混合压测让每个 worker 轮流请求四个接口，
整体速度由较慢的会话和指标接口决定；这不代表同时压四个接口可以线性叠加容量。

## 如何解读

- 5 并发时客户端 worker 数量是瓶颈，RPS 最高但延迟只反映轻载路径。
- 并发从 50 提高到 100，吞吐基本持平（约 172 RPS），P95 从约 461 ms 升到
  约 855 ms。说明在当前单 worker 部署下，请求在服务端排队，而不是继续线性扩容。
- 50 并发时成功率为 100%，说明演示规模下的只读查询没有数据库连接耗尽、
  超时或限流错误；100 并发时出现一次未复现的 502，不能据此声称“100 并发稳定”。
- 本次只覆盖读路径。模型生成、RAG 检索、MCP 调用和高风险写操作不在结果内，
  不能把这里的 RPS 当作数字员工完整任务的处理能力。

## 局限

- 压测客户端和 API 在同一台机器上，Docker Desktop 的 NAT 和资源竞争会影响结果。
- 单 uvicorn worker 是当前演示栈的配置，没有验证多 worker 横向扩展。
- 四个接口混合统计，没有按接口拆分延迟；需要定位慢接口时用 `--path` 单独复测。
- 没有模拟真实用户思考时间、登录流程、SSE 长连接和写操作。
- 本地数据集规模有限，缓存和数据库统计信息会随数据量变化。

## 下一步

生产级压测应使用独立负载机、固定数据集、多 worker 部署，并分别覆盖读路径、
知识检索、模型生成、MCP 调用、审批写入和 SSE，给出各接口 P95 / P99、错误率、
数据库连接池和 CPU/内存水位，而不是只报一个总 RPS。

## 写路径并发验收（会话运行时）

只读基线不覆盖写操作。会话运行时的写路径另有一个可重复的并发验收脚本：

```text
cd apps/api
uv run python scripts/stress_runtime_concurrency.py http://127.0.0.1:8000 -n 20
```

它直接对运行中的真实栈发起“买家消息 vs 人工接管”“同一
`client_message_id` 重复提交”“两条消息并发”三组竞态，并用 psycopg 读取
PostgreSQL 断言结果（轮次终态、`CANCELLED` 无回复、接管后无新回复、
单工单、序号互异、取消轮次不可重试）。脚本自建 `stress_agent_*` 员工与
知识，结束时通过 `archive-test-data` 归档。

接管与在途轮次会互相等待行锁，PostgreSQL 以 SQLSTATE `40P01` 中止一方；
应用侧对两类受害者都做了有界重试（接管 3 次、worker 轮次 2 次），重试耗尽
才交给租约回收。因此 `postgres` 日志里仍会出现 `deadlock detected`，只要
API 没有 `ERROR` 且所有轮次收敛到终态，就属于已处理路径。
