# Prometheus 配置

`prometheus.yml` 默认抓取宿主机的 `host.docker.internal:8000/metrics`。
生产环境应把目标替换为实际服务 DNS，并通过 `authorization` 配置
`METRICS_SCRAPE_TOKEN`，不要使用无鉴权公网端点。

`alerts.yml` 包含：

- 外部同步失败率超过 10%。
- 重试积压超过 20 张。
- RAG 引用覆盖率低于 80%。
- 政策主张引用覆盖率低于 95%。
- 语义 Judge 发现未支持主张。

告警阈值需要在真实流量基线上校准。

`prometheus.yml` 的 `alerting` 段把告警投递到 compose 内的
`alertmanager:9093`。Alertmanager 的路由与抑制规则见
`../alertmanager/alertmanager.yml`：

- `critical` 10 秒后首投，1 小时重复。
- `warning` 30 秒后首投，4 小时重复。
- 同一 `alertname` + `business_unit` 的 critical 会抑制对应 warning。
- webhook URL 不写入配置，由容器启动时从 `ALERT_WEBHOOK_URL` 写入
  `/tmp/alert_webhook_url`，供 `url_file` 读取；`send_resolved` 已开启。
- Alertmanager 固定为 `v0.28.1`：`v0.27.0` 在接收端返回非 2xx
  （如 relay 返回 502）时会 panic 退出；0.28.1 已验证只重试、不崩溃。

本地验证：

```bash
make observability-up
curl -s http://localhost:9093/-/healthy
curl -s http://localhost:9090/api/v1/alertmanagers

# Grafana 健康、默认数据源与自动导入的看板
curl -s -u admin:admin http://localhost:3000/api/health
curl -s -u admin:admin http://localhost:3000/api/datasources
curl -s -u admin:admin 'http://localhost:3000/api/search?type=dash-db'

# /metrics 鉴权：无令牌 401，带 token 200
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/metrics
curl -s -H "Authorization: Bearer $METRICS_SCRAPE_TOKEN" \
  http://localhost:8000/metrics | grep '^ticket_worker_workflow_'
```

`.env` 未设置 `METRICS_SCRAPE_TOKEN` 时，API 与 Prometheus 共用 compose
默认值 `local-metrics-token`；生产必须改为独立强随机值。

## 飞书群机器人接入

链路是 `Prometheus → Alertmanager → alert-relay → 飞书群自定义机器人`。
接入步骤：

1. 在目标飞书群 → 设置 → 群机器人 → 添加机器人 → 自定义机器人，复制
   webhook 地址（形如 `https://open.feishu.cn/open-apis/bot/v2/hook/<token>`）。
2. 如需签名校验，在机器人安全设置里勾选“签名校验”，复制密钥。
3. 写入本机 `.env`（不要提交到仓库或贴进聊天）：

```bash
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/<token>
FEISHU_WEBHOOK_SECRET=<签名密钥>   # 未开启签名校验则留空
```

4. 先做单条自检，确认机器人真的能收到消息：

```bash
make observability-feishu-test
# result: ok ({"code":0}) 表示 webhook 与签名都被接受
```

自检与正式告警默认发送 `interactive` 卡片：标题按状态配色
（critical 红、warning 橙、resolved 绿），正文包含告警规则、级别、业务线、
摘要、描述和开始时间；单条最多展开 8 个告警。需要回退纯文本时在 `.env`
设置 `FEISHU_MESSAGE_FORMAT=text`。

5. 自检通过后再拉起完整链路：

```bash
make observability-feishu-up
```

常见失败：

- `FEISHU_WEBHOOK_URL is required in .env`：第 3 步未写入或 `.env` 路径不对。
- `feishu code=19021`：签名不匹配，通常是 `FEISHU_WEBHOOK_SECRET` 与机器人
  后台不一致，或机器人开启了签名校验但本地没配。
- `feishu code=19024` 等：机器人被移出群、webhook 已失效，需要重新添加。
- relay 返回 502：飞书侧失败，Alertmanager 会按退避重试，不会丢告警。

生产环境还应把 `FEISHU_WEBHOOK_URL` 作为密钥管理，不写进镜像或提交记录。

未设置 `ALERT_WEBHOOK_URL` 时启动日志会打印 WARN，并回落到
`host.docker.internal:9999/alerts`，仅用于本机验证；生产环境必须设置
真实接收端，否则告警不会离开当前环境。

## 飞书群自定义机器人

`../alert-relay/relay.py` 把 Alertmanager 原生 webhook payload 转成飞书
文本消息并转发，支持签名校验。relay 只暴露在 compose 网络内，不对宿主机
发布端口。

```bash
# .env 中设置：
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
FEISHU_WEBHOOK_SECRET=机器人签名密钥   # 未开启签名校验时留空

make observability-feishu-up
```

`make observability-feishu-up` 会以
`ALERT_WEBHOOK_URL=http://alert-relay:8080/alerts` 启动 Alertmanager，
链路为 Prometheus → Alertmanager → alert-relay → 飞书群。

行为约定：

- 飞书返回成功（`code == 0`）时 relay 返回 200。
- 飞书返回业务错误或传输失败时 relay 返回 502，让 Alertmanager 重试；
  配合 0.28.1 不会导致 Alertmanager 退出。
- 接收端恢复后，积压的重试会在下一次退避窗口内送达。
- `GET /healthz` 用于容器健康检查。


