# OnDuty · 数字员工平台

[![CI](https://github.com/github0117/onduty-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/github0117/onduty-platform/actions/workflows/ci.yml)

一个多租户数字员工平台：把企业知识、岗位规程（Skill）、模型和 MCP 业务工具，
装配成可上岗、可评测、可审批、可接管、可审计的 AI Agent。

主演示是**企业服务台**：同一入口按问题自动分派研发支持、HR 和企业服务台员工；
电商客服用于验证商品咨询、订单物流、退款审批、人工接管和失败恢复闭环。

<!-- GitHub 的 README 只允许 user-attachments 视频从 S3 播放；部分 Chrome 网络无法访问
     该域名，播放器会停在 0:00。这里用仓库内 60 秒全幅动图做浏览器通用内嵌演示，
     带进度条的 MP4 作为下载版本。 -->
<img src="docs/assets/demo/on-duty-routing-demo.gif" width="100%" alt="OnDuty 数字员工平台 60 秒演示：同一入口跨岗位分派">

> **60 秒完整演示**：同一入口跨岗位分派 → 员工能力快照 → 意图冲突检查 → 路由评测。
> 上图为完整演示动图（循环播放），Chrome / Safari 均可直接观看；带进度条的 MP4 见下方下载链接。
>
> [MP4 下载](https://github.com/github0117/onduty-platform/raw/main/docs/assets/demo/on-duty-routing-demo.mp4) · [WebM 原片](https://github.com/github0117/onduty-platform/raw/main/docs/assets/demo/on-duty-routing-demo.webm) · [8 秒轻量预览](docs/assets/demo/on-duty-routing-demo-preview.gif)

## 界面预览

| 企业服务台 Agent | 业务入口与员工池 |
| --- | --- |
| <img src="docs/assets/screenshots/customer-service-enterprise.png" alt="企业服务台 Agent" width="480"> | <img src="docs/assets/screenshots/employee-routing.png" alt="业务入口与员工池" width="480"> |
| **知识库** | **电商上架审核** |
| <img src="docs/assets/screenshots/knowledge.png" alt="知识库" width="480"> | <img src="docs/assets/screenshots/ecommerce.png" alt="电商上架审核" width="480"> |

## 核心能力

- **数字员工装配**：岗位模板、员工、角色提示词、Skill、知识空间、MCP 授权和
  模型策略统一建模；配置版本化，资源变化后自动回到试用并重新评测。
- **入口路由与评测**：业务入口绑定员工池，按意图、关键词和本地语义分派；
  记录候选、分数和排除原因，支持 TUNING / HOLDOUT 评测集与失败分析。
- **RAG 与引用**：知识空间授权检索、文档版本与发布门禁、引用声明校验；
  无依据或校验不通过时转人工，不编造答案。
- **MCP 工具治理**：只读工具自动执行；写工具走确定性策略、独立审批、
  幂等执行、事故对账与补偿审批。
- **客服工作台**：SSE 流式回复、自动派单、人工接管、风险分级、SLA、
  回复建议、反馈修复和审计。
- **多租户与可靠性**：资源级租户校验、统一 403、幂等键、工单状态机白名单、
  限流和请求体上限。
- **服务端 RBAC**：角色到能力只由后端维护，`GET /api/v1/me` 下发能力快照；
  菜单、路由和按钮按同一清单渲染，越权页面显示 403，只读角色不出现写操作入口。

## 系统架构

```mermaid
flowchart LR
  Web["React + Vite 前端"] --> Nginx["Nginx"]
  Nginx --> API["FastAPI API"]
  API --> PG[("PostgreSQL<br/>+ pgvector")]
  API --> Redis[("Redis")]
  API --> Store[("对象存储<br/>本地卷 / S3 兼容")]
  Redis --> Worker["Celery Worker"]
  Worker --> PG
  Worker --> Store
  Worker --> Biz["业务系统 / MCP 工具"]
  Beat["Celery Beat"] --> Redis
  Prom["Prometheus"] -. "/metrics 抓取" .-> API
  Grafana["Grafana"] --> Prom
```

## 快速开始

需要 Docker、`make`、`uv`、Node.js 和 pnpm：

```bash
make install   # uv sync + pnpm install
make build     # 构建前端到 apps/web/dist
docker compose -f infra/compose/docker-compose.yml --profile app up -d
```

首次打开演示环境会以平台管理员进入“平台总览”，可先查看各类内容的真实数量，
再点击“进入 60 秒主演示”。需要补齐固定数据时，进入“运行与审计”点击
“检查并恢复演示数据”；任务只作用于 `bu_demo`，在后台执行并轮询状态，也可以
直接执行 `make seed-demo`。页头可切换客服坐席、客服主管、知识运营、业务经理、
审计员和平台管理员六种演示身份，菜单、按钮和页面访问权限随身份即时变化。

- 平台总览：<http://127.0.0.1:5173/overview>
- 主演示 · 企业服务台：<http://127.0.0.1:5173/customer-service>
- 人工工作台：<http://127.0.0.1:5173/customer-service/workbench>
- 电商运营：<http://127.0.0.1:5173/ecommerce>
- 数字员工：<http://127.0.0.1:5173/employees/roster>
- API 文档：<http://127.0.0.1:5173/docs>

## 验证

```bash
make test          # 后端测试
make lint          # Ruff
make typecheck     # mypy + TypeScript
make build         # Vite production build
make e2e-web       # Playwright 浏览器回归

# 跨租户越权回归
cd apps/api && uv run pytest tests/integration/test_tenant_resource_access.py -v

# 最终一键验收
make acceptance-final
```

当前基线：

```text
后端: 405 passed（含 PostgreSQL/pgvector 专项）
Python 覆盖率: 88%（CI 门槛 85%）
路由评测: TUNING 36/36；HOLDOUT 16/18（88.9%，含失败分析）
Ruff / mypy: passed（177 个源文件）
TypeScript / Vite: passed
Playwright: 148 passed, 2 skipped（25 个测试文件）
只读并发: 50/100 并发，P95 460.89 / 850.71 ms
PostgreSQL migration: e7a1c3d5b9f2 (head)
模拟业务系统: passed（成功、幂等、HTTP 500 故障）
```

## 技术栈

React + TypeScript + Ant Design · FastAPI + SQLAlchemy + Alembic ·
PostgreSQL + pgvector · Redis + Celery · LangGraph · MCP Python SDK ·
Playwright · Docker Compose · Nginx · FFmpeg

## 项目文档

- [演示与验收说明](docs/demo-guide.md)：项目定位、7 分钟演示脚本、指标口径和验收证据
- [完整能力清单](docs/features.md)：平台全部功能细节
- [模型与外部集成配置](docs/configuration.md)：千问、物流、限流和请求体上限
- [多租户隔离设计与回归验证](docs/tenant-isolation.md)
- [只读并发压测](docs/load-test.md)

## 当前限制

- 演示栈运行在本地 Compose，业务系统使用 Mock Business，尚未接入真实企业订单、
  物流和资金系统。
- 语义路由使用本地确定性文本相似度，未调用外部 Embedding 或语义模型。
- 视频使用程序化镜头效果，未接入图生视频模型；BGM 需上传已获授权的音频。
- MCP 当前只支持 Streamable HTTP；写操作必须审批，结果不确定时进入事故对账，
  不会自动重试。
- 生产级压测、企业 OIDC、真实消息渠道和安全评审仍待完成。
