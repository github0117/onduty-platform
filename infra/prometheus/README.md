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
```

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


