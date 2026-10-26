#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$repo_root/infra/compose/docker-compose.yml"
corpus_dir="$repo_root/outputs/acceptance/corpus"
# api 容器以非 root 用户运行，/app 不可写；/tmp 是可写的临时目录，
# 语料只在播种时读取，不需要持久化。
container_dir="/tmp/acceptance-corpus"

if [[ ! -d "$corpus_dir" ]]; then
  printf '缺少本地验收语料：%s\n' "$corpus_dir" >&2
  printf '请先运行 apps/api/scripts/prepare_acceptance_corpus.py 生成语料。\n' >&2
  exit 1
fi

# outputs/ 不随仓库发布，因此语料不能靠 bind mount 提供。api 容器启动后
# 再把本地语料复制进去，全新克隆也能跑完验收。
docker compose -f "$compose_file" exec -T api mkdir -p "$container_dir"
docker compose -f "$compose_file" cp "$corpus_dir/." "api:$container_dir"
