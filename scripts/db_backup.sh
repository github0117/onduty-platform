#!/usr/bin/env bash
# 备份 PostgreSQL 到 backups/ 目录，并校验备份可被 pg_restore 读取。
# 只通过 compose 里的 postgres 容器执行，不依赖宿主机安装 psql。
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$repo_root/infra/compose/docker-compose.yml"
if [ -f "$repo_root/.env" ]; then
  export COMPOSE_ENV_FILES="$repo_root/.env"
fi
backup_dir="${BACKUP_DIR:-$repo_root/backups}"
retain="${BACKUP_RETAIN:-7}"
postgres_user="${POSTGRES_USER:-ticket_agent}"
postgres_db="${POSTGRES_DB:-ticket_agent}"

mkdir -p "$backup_dir"

if ! docker compose -f "$compose_file" ps --status running --services 2>/dev/null | grep -qx postgres; then
  printf 'postgres 服务未运行，请先执行 make stack-up\n' >&2
  exit 1
fi

timestamp="$(TZ=Asia/Shanghai date '+%Y%m%d-%H%M%S')"
target="$backup_dir/ticket_agent-$timestamp.dump"
partial="$target.partial"
cleanup() { rm -f "$partial"; }
trap cleanup EXIT

printf '==> 导出 %s/%s 到 %s\n' "$postgres_user" "$postgres_db" "$target"
docker compose -f "$compose_file" exec -T postgres \
  pg_dump -U "$postgres_user" -d "$postgres_db" --format=custom --no-owner \
  >"$partial"

if [ ! -s "$partial" ]; then
  printf '导出结果为空，已放弃保留\n' >&2
  exit 1
fi

if ! docker compose -f "$compose_file" exec -T postgres pg_restore --list \
  <"$partial" >/dev/null; then
  printf '导出文件未通过 pg_restore --list 校验\n' >&2
  exit 1
fi

mv "$partial" "$target"

revision="unknown"
if docker compose -f "$compose_file" ps --status running --services 2>/dev/null | grep -qx api; then
  revision="$(
    docker compose -f "$compose_file" exec -T api alembic current 2>/dev/null \
      | awk 'NR==1 {print $1}'
  )"
  revision="${revision:-unknown}"
fi
printf '%s\n' "$revision" >"$target.migration"

printf '==> 备份完成：%s（%s，迁移版本 %s）\n' \
  "$target" "$(du -h "$target" | cut -f1)" "$revision"

# 只保留最近 retain 份；macOS 自带 bash 3.2 没有 mapfile，用管道逐行处理。
ls -1t "$backup_dir"/ticket_agent-*.dump 2>/dev/null \
  | tail -n +"$((retain + 1))" \
  | while IFS= read -r old; do
      rm -f "$old" "$old.migration"
      printf '==> 轮转删除 %s\n' "$old"
    done
