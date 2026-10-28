# 上线检查清单（试点部署）

适用范围：用 `infra/compose/docker-compose.yml` 交付的单机试点环境。
本清单把“每次部署都要人工确认”的项收敛成可执行命令；能自动判定的部分由
`scripts/preflight_check.sh` 完成，其余项仍需人工签字确认。

> 未验收边界：本清单覆盖演示栈与单机试点。企业 OIDC、真实 ERP/CRM/物流/消息渠道、
> 多副本部署与生产级备份策略不在本轮验收范围内，见 `outputs/15_最终验收报告.md`。

## 1. 部署前

| 项 | 命令 | 期望 |
| --- | --- | --- |
| 配置文件存在 | `test -f .env` | 存在；缺失时检索为演示模式 |
| 密钥只在 `.env` | 检查 `.env` 已加入 `.gitignore`，仓库与镜像内无密钥 | compose 文件中不出现明文密钥 |
| compose 可解析 | `docker compose -f infra/compose/docker-compose.yml config -q` | 无输出、退出码 0 |
| 迁移目录随镜像 | `docker compose -f infra/compose/docker-compose.yml run --rm --no-deps migrate ls migrations/versions` | 与仓库 `apps/api/migrations/versions` 一致 |
| 备份现有库 | `make db-backup` | 输出备份路径，且通过 `pg_restore --list` 校验 |

`.env` 说明：

- compose 的 `${VAR:-default}` 插值通过 `COMPOSE_ENV_FILES` 读取**仓库根** `.env`
  （Makefile 与 `scripts/*.sh` 已自动设置）。直接把变量写进根 `.env` 即可，
  不需要 export，也不需要复制到 `infra/compose/.env`。
- 主模型只认 `MODEL_BASE_URL / MODEL_API_KEY / MODEL_NAME`，不再复用
  `ECOMMERCE_CONTENT_*`；两套密钥互不覆盖。

## 2. 部署

```bash
make stack-up          # 构建镜像 + 启动 app profile（含 migrate）
```

migrate 服务现在依次执行：

1. `migration_preflight.py --allow-pending`：数据库版本必须是本镜像可达的版本；
   若是本镜像不认识的新版本（回滚场景），立即失败退出。
2. `alembic upgrade head`。
3. `migration_preflight.py --expect-head`：确认恰好落在 head。

任一步失败，migrate 容器以非 0 退出，`api` 因 `service_completed_successfully`
不会启动——不会出现“服务起来了但表结构不对”的状态。

## 3. 部署后

```bash
./scripts/preflight_check.sh            # 只读检查
./scripts/preflight_check.sh --smoke    # 追加真实接口烟测（会写演示数据）
```

检查项：`.env` 存在、compose 可解析、无硬编码密钥、postgres/redis/api/worker/beat/web
运行中、迁移版本在 head、`/health/live` 与 `/health/ready` 返回 200、嵌入模式、鉴权模式。
任一 FAIL 退出码为 1。

人工确认：

- [ ] 页面可打开：`http://<host>:5173`
- [ ] `GET /health/ready` 返回 `{"status":"ok","database":"ok"}`
- [ ] 若 `EMBEDDING_API_KEY` 已配置：执行 `POST /api/v1/knowledge/reindex` 并确认
      任务 SUCCEEDED，页面提示不再是“本地哈希演示模式”
- [ ] 若 `APP_AUTH_MODE=dev`：确认该环境仅供演示，不对外暴露

## 4. 回滚

顺序：先停业务，再恢复数据，最后启动旧镜像。

```bash
make stack-down                                  # 停 web/api/worker/beat/migrate
./scripts/db_restore.sh backups/<dump> --yes     # 停服务、校验备份、单事务恢复
# 切回上一版镜像后
make stack-up
./scripts/preflight_check.sh
```

- 恢复脚本要求显式 `--yes`，恢复前用 `pg_restore --list` 校验备份完整性。
- 如果备份版本落后于镜像 head，脚本会提示执行 `make stack-up` 让 migrate 升级。
- 如果数据库版本**领先**于镜像（回滚到旧镜像），migrate 的 `--allow-pending` 检查
  会直接失败——这正是要发生的行为：旧代码不碰新表结构，用备份回退或前滚。

## 5. 已知边界

- `APP_ENV=production` 与 `APP_AUTH_MODE=oidc` 的完整链路未在本轮验收；切换前需另行
  验收 OIDC 登录、角色映射与跨租户隔离。
- compose 中的 `POSTGRES_PASSWORD: ticket_agent` 与 `METRICS_SCRAPE_TOKEN` 是本地
  演示默认值，生产部署必须替换（`preflight_check.sh` 会给出 WARN）。
- 备份为单次全量 `pg_dump`，保存于 `backups/`（已忽略提交），默认保留最近 7 份；
  没有异地副本与定时任务，长期运行需接入外部备份系统。
