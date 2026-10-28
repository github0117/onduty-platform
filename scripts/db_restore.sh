#!/usr/bin/env bash
# 用 db_backup.sh 生成的备份恢复数据库。
#
# 这是破坏性操作：会先停掉 api/worker/beat（释放连接），再用 --clean 覆盖现有
# 库中的全部对象。必须显式传 --yes；恢复后不会自动拉起服务，由操作人决定。
set -euo pipefail

usage() {
  printf '用法: %s <dump 文件> --yes\n' "$(basename "$0")" >&2
  exit 64
}

dump="${1:-}"
confirm="${2:-}"
[ -n "$dump" ] && [ "$confirm" = "--yes" ] || usage

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$repo_root/infra/compose/docker-compose.yml"
if [ -f "$repo_root/.env" ]; then
  export COMPOSE_ENV_FILES="$repo_root/.env"
fi
postgres_user="${POSTGRES_USER:-ticket_agent}"
postgres_db="${POSTGRES_DB:-ticket_agent}"

if [ ! -f "$dump" ]; then
  printf '备份文件不存在: %s\n' "$dump" >&2
  exit 1
fi

printf '==> 校验备份文件\n'
if ! docker compose -f "$compose_file" exec -T postgres pg_restore --list \
  <"$dump" >/dev/null; then
  printf '备份文件未通过 pg_restore --list 校验，已中止\n' >&2
  exit 1
fi

if ! docker compose -f "$compose_file" ps --status running --services 2>/dev/null | grep -qx postgres; then
  printf 'postgres 服务未运行，请先执行 make stack-up 只启动依赖\n' >&2
  exit 1
fi

printf '==> 停止 api / worker / beat 以释放数据库连接\n'
docker compose -f "$compose_file" stop api worker beat >/dev/null 2>&1 || true

printf '==> 恢复 %s 到 %s/%s（覆盖现有数据）\n' "$dump" "$postgres_user" "$postgres_db"
docker compose -f "$compose_file" exec -T postgres \
  pg_restore -U "$postgres_user" -d "$postgres_db" \
  --clean --if-exists --no-owner --single-transaction \
  <"$dump"

printf '==> 检查恢复后的迁移版本\n'
status=0
docker compose -f "$compose_file" --profile app run --rm --no-deps -T migrate \
  python scripts/migration_preflight.py || status=$?

case "$status" in
  0)
    printf '==> 恢复完成，数据库版本与镜像 head 一致\n'
    ;;
  3)
    printf '==> 恢复完成，数据库版本落后于镜像 head；执行 make stack-up 让 migrate 升级\n'
    ;;
  *)
    printf '==> 恢复完成，但数据库版本无法被当前镜像识别，请人工确认\n' >&2
    exit 1
    ;;
esac

printf '==> 服务仍处于停止状态；确认无误后执行 make stack-up 启动\n'
