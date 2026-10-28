#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log_dir="$repo_root/outputs/acceptance"
report_path="$repo_root/outputs/15_最终验收报告.md"
compose_file="$repo_root/infra/compose/docker-compose.yml"
# compose 的 ${VAR:-default} 插值只读项目目录（infra/compose）的 .env；
# 显式指定仓库根 .env，保证本机密钥与配置真正进入容器。
if [ -f "$repo_root/.env" ]; then
  export COMPOSE_ENV_FILES="$repo_root/.env"
fi
mkdir -p "$log_dir"
rm -f "$log_dir"/*.log "$report_path"

steps=()

run_step() {
  local name="$1"
  local directory="$2"
  shift 2
  local log_file="$log_dir/$name.log"
  printf '==> %s\n' "$name"
  if (cd "$repo_root/$directory" && "$@") >"$log_file" 2>&1; then
    steps+=("| $name | PASSED | \`$log_file\` |")
    return
  fi
  steps+=("| $name | FAILED | \`$log_file\` |")
  write_report "FAILED"
  tail -80 "$log_file"
  exit 1
}

write_report() {
  local status="$1"
  {
    printf '# 数字员工平台最终验收报告\n\n'
    printf '日期：%s  \n' "$(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S')"
    printf '结论：**%s**  \n' "$status"
    printf '环境：Docker Compose、PostgreSQL、Redis、本地对象存储、Celery、模拟业务系统\n\n'
    printf '## 验收结果\n\n'
    printf '| 验收项 | 结果 | 日志 |\n'
    printf '|---|---|---|\n'
    printf '%s\n' "${steps[@]}"
    printf '\n## 验收边界\n\n'
    printf -- '- 企业服务台、电商客服和内部工单使用真实运行服务与模拟业务数据。\n'
    printf -- '- 外部订单、物流、工单和电商发布由 Mock Business 服务模拟，不代表生产接口已联调。\n'
    printf -- '- 业务收益为模拟环境指标，不能直接作为真实投资回报。\n'
    printf -- '- 企业 OIDC、真实 ERP/CRM/支付/物流和外部消息渠道仍需生产接入验收。\n'
  } >"$report_path"
}

run_step web-build apps/web ./node_modules/.bin/tsc --noEmit
run_step vite-build apps/web ./node_modules/.bin/vite build
run_step python-tests apps/api .venv/bin/pytest -q
run_step ruff apps/api .venv/bin/ruff check .
run_step mypy apps/api .venv/bin/mypy src
run_step acceptance-corpus apps/api .venv/bin/python scripts/prepare_acceptance_corpus.py "$repo_root/outputs/acceptance/corpus"

run_step compose-up . docker compose -f "$compose_file" --profile app up -d --build migrate api worker beat web mock-business
run_step acceptance-corpus-sync . ./scripts/sync_acceptance_corpus.sh
run_step acceptance-seed . docker compose -f "$compose_file" exec -T api python scripts/seed_acceptance_corpus.py http://127.0.0.1:8000 /tmp/acceptance-corpus
run_step migration-head . docker compose -f "$compose_file" exec -T api alembic current
run_step stack-smoke . docker compose -f "$compose_file" exec -T api python scripts/acceptance_real_infra.py http://127.0.0.1:8000
run_step mock-business . docker compose -f "$compose_file" exec -T api python scripts/acceptance_mock_systems.py http://mock-business:8090

docker compose -f "$compose_file" --profile app --profile test rm -sf e2e >/dev/null 2>&1 || true
run_step browser-e2e . docker compose -f "$compose_file" --profile app --profile test up --abort-on-container-exit --exit-code-from e2e e2e

write_report "PASSED"
printf '最终验收通过：%s\n' "$report_path"
