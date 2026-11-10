# 可观测性与告警

平台的运行指标由 `apps/api` 的 `GET /metrics` 暴露，Prometheus 抓取，Grafana 展示，
Alertmanager 负责规则触达后的外发。这一层只监控平台自身（死信、积压、重试、
引用覆盖率、模型预算、限流），不参与业务响应。

## 启动

```bash
make observability-up          # Prometheus + Alertmanager + Grafana
make observability-feishu-up   # 额外拉起 alert-relay，把告警推到飞书群
```

| 服务 | 地址 | profile |
| --- | --- | --- |
| Prometheus | <http://127.0.0.1:9090> | `observability` |
| Alertmanager | <http://127.0.0.1:9093> | `observability` |
| Grafana | <http://127.0.0.1:3000>（admin / admin） | `observability` |
| alert-relay | 仅 compose 网络内 `:8080`，不映射宿主机 | `feishu-alerts` |

`make stack-up` 与 `--profile app` 都不包含这套栈。

## 告警规则

规则在 [`infra/prometheus/alerts.yml`](../infra/prometheus/alerts.yml)，分两组：

- `ticket-digital-worker`：外部同步失败率与重试积压、RAG 无依据/引用覆盖率、模型预算预测与超限、限流拒绝。
- `ticket-workflow-engine`：死信、待执行步骤堆积、最老积压超 30 分钟、重试风暴、租约回收空转。

每条规则都有 `for` 持续时间和 `severity`（`warning` / `critical`），
`send_resolved` 已开启，恢复时会补一条恢复通知。

## 告警外发

Alertmanager 的 webhook 来自 `ALERT_WEBHOOK_URL`，启动时写成 `0600` 临时文件供
`url_file` 读取。留空时只打印 WARN 并回落到 `host.docker.internal:9999/alerts`，
即告警不会离开本机。

### 飞书群自定义机器人

`alert-relay` 是一个无状态 sidecar：接收 Alertmanager 原生 webhook，转换成飞书
卡片（默认）或纯文本，POST 到群机器人 webhook。鉴权用 URL 里的 token，另支持
`timestamp + "\n" + secret` 的 HMAC-SHA256 签名。

```bash
# .env
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/<token>
FEISHU_WEBHOOK_SECRET=        # 群机器人开启签名时填
FEISHU_MESSAGE_FORMAT=card    # 设为 text 可回退纯文本
```

```bash
make observability-feishu-test   # 直连飞书发一条自检消息，不经过 Alertmanager
make observability-feishu-up     # 拉起完整链路
```

`alert-relay` 启动时校验 URL，缺失或非法会以退出码 1 拒绝启动；`SECRET` 为空只
WARN 不退出。消息只在 Alertmanager 触发告警并 POST 到 `/alerts` 时发出，进程常驻
不等于会推送。

排障：`docker logs alert-relay` 看转换与投递结果；Alertmanager UI 的 Alerts 页
确认规则是否触发；`make observability-feishu-test` 失败说明 webhook 或签名有问题，
与 Prometheus 无关。

完整的容器细节、token 落盘方式和历史问题（Alertmanager 0.27.0 在接收端返回非
2xx 时会 panic 退出，已升级到 0.28.1）见
[`infra/prometheus/README.md`](../infra/prometheus/README.md)。

## 覆盖范围

飞书外发链路默认不启动，也不在 CI 覆盖范围内；没有配置 `FEISHU_WEBHOOK_URL`
时整条链路不会生效，平台其余功能不受影响。指标采集与 Grafana 面板是常驻能力。
