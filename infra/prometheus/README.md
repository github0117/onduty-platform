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

