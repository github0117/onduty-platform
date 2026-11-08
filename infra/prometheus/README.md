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

本地验证：

```bash
make observability-up
curl -s http://localhost:9093/-/healthy
curl -s http://localhost:9090/api/v1/alertmanagers
```

未设置 `ALERT_WEBHOOK_URL` 时启动日志会打印 WARN，并回落到
`host.docker.internal:9999/alerts`，仅用于本机验证；生产环境必须设置
真实接收端，否则告警不会离开当前环境。

