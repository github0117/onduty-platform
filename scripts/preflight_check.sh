#!/usr/bin/env bash
# 上线前检查：把 15_最终验收报告 里靠人工确认的几项变成可执行检查。
#
# 只读：不启动、不停止、不改写任何服务或数据。任一项 FAIL 时退出码为 1。
# 用法: ./scripts/preflight_check.sh [--smoke]
set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$repo_root/infra/compose/docker-compose.yml"
env_file="$repo_root/.env"
if [ -f "$env_file" ]; then
  export COMPOSE_ENV_FILES="$env_file"
fi
run_smoke=false

for argument in "$@"; do
  case "$argument" in
    --smoke) run_smoke=true ;;
    *) printf '未知参数: %s\n' "$argument" >&2; exit 64 ;;
  esac
done

failures=0
warnings=0

pass() { printf '[PASS] %s\n' "$1"; }
warn() { printf '[WARN] %s\n' "$1"; warnings=$((warnings + 1)); }
fail() { printf '[FAIL] %s\n' "$1"; failures=$((failures + 1)); }

running_services() {
  docker compose -f "$compose_file" ps --status running --services 2>/dev/null
}

printf '==> 上线前检查（%s）\n' "$(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S')"

# 1. 本机 .env：密钥只允许从这里注入，不进入镜像或仓库。
if [ -f "$env_file" ]; then
  pass ".env 存在（密钥只从本机注入）"
else
  warn ".env 不存在；未配置模型/嵌入密钥时将以本地演示模式运行"
fi

# 2. compose 文件本身可解析。
if docker compose -f "$compose_file" config -q >/dev/null 2>&1; then
  pass "compose 配置可解析"
else
  fail "compose 配置无法解析（docker compose config -q 失败）"
fi

# 3. compose 文件不得硬编码真实密钥；开发默认值只提示不阻断。
# 不用 grep -n：行号前缀里的冒号会被下面的“长值”正则误判成密钥。
hardcoded="$(grep -E '^[[:space:]]+[A-Z0-9_]*(API_KEY|SECRET|ACCESS_TOKEN|PASSWORD)[[:space:]]*:[[:space:]]*[^$[:space:]]' "$compose_file" 2>/dev/null || true)"
if [ -z "$hardcoded" ]; then
  pass "compose 文件未硬编码 API 密钥"
else
  serious="$(printf '%s\n' "$hardcoded" | grep -E 'sk-|AKIA|:[[:space:]]*[A-Za-z0-9/+_-]{24,}' || true)"
  if [ -n "$serious" ]; then
    fail "compose 文件疑似硬编码真实密钥："
    printf '%s\n' "$serious" | sed 's/^/       /'
  else
    warn "compose 文件含开发默认口令（仅限本地演示栈）："
    printf '%s\n' "$hardcoded" | sed 's/^/       /'
  fi
fi

# 4. 关键服务在运行。
services="$(running_services)"
for required in postgres redis api; do
  if printf '%s\n' "$services" | grep -qx "$required"; then
    pass "$required 服务运行中"
  else
    fail "$required 服务未运行"
  fi
done
for optional in worker beat web; do
  if printf '%s\n' "$services" | grep -qx "$optional"; then
    pass "$optional 服务运行中"
  else
    warn "$optional 服务未运行（异步任务、定时任务或页面将不可用）"
  fi
done

# 5. 数据库迁移版本必须恰好落在镜像的 head。
if printf '%s\n' "$services" | grep -qx api; then
  if migration_output="$(docker compose -f "$compose_file" exec -T api \
    python scripts/migration_preflight.py --expect-head 2>&1)"; then
    pass "迁移版本在 head（$(printf '%s' "$migration_output" | head -1)）"
  else
    fail "迁移版本不在 head（$(printf '%s' "$migration_output" | head -1)）"
  fi

  # 6. 存活与就绪探针。
  for probe in live ready; do
    if docker compose -f "$compose_file" exec -T api python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/$probe', timeout=5)" \
      >/dev/null 2>&1; then
      pass "/health/$probe 返回 200"
    else
      fail "/health/$probe 未返回 200"
    fi
  done

  # 7. 检索质量模式：没有嵌入密钥就是演示模式，生产上必须显式知悉。
  embedding_key="$(docker compose -f "$compose_file" exec -T api \
    sh -c 'printf "%s" "${EMBEDDING_API_KEY:-}"' 2>/dev/null || true)"
  app_env="$(docker compose -f "$compose_file" exec -T api \
    sh -c 'printf "%s" "${APP_ENV:-development}"' 2>/dev/null || true)"
  if [ -n "$embedding_key" ]; then
    pass "已配置语义嵌入密钥（embedding_quality=semantic）"
  else
    warn "未配置 EMBEDDING_API_KEY；检索为 local-hash 演示模式（embedding_quality=demo）"
  fi
  if [ "$app_env" = "production" ] && [ -z "$embedding_key" ]; then
    warn "APP_ENV=production 但仍在演示嵌入模式，对外不得称为语义检索"
  fi

  # 8. 鉴权模式：dev 模式下身份由请求头决定，只有演示环境可以接受。
  auth_mode="$(docker compose -f "$compose_file" exec -T api \
    sh -c 'printf "%s" "${APP_AUTH_MODE:-dev}"' 2>/dev/null || true)"
  if [ "$auth_mode" = "dev" ]; then
    warn "APP_AUTH_MODE=dev：身份由请求头决定，仅限演示；生产必须切换 OIDC"
  else
    pass "鉴权模式为 $auth_mode"
  fi
fi

# 8. 可选全栈烟测（真实接口写读，会创建演示数据）。
if [ "$run_smoke" = true ]; then
  if docker compose -f "$compose_file" exec -T api \
    python scripts/acceptance_real_infra.py http://127.0.0.1:8000; then
    pass "全栈烟测通过"
  else
    fail "全栈烟测失败"
  fi
fi

printf '==>\n'
if [ "$failures" -gt 0 ]; then
  printf '==> 结论：FAIL（%s 项失败，%s 项警告）\n' "$failures" "$warnings"
  exit 1
fi
printf '==> 结论：PASS（%s 项警告）\n' "$warnings"
