UV_CACHE_DIR := $(CURDIR)/.cache/uv
UV_RUN_FLAGS ?= --offline
export UV_CACHE_DIR

# compose 的 ${VAR:-default} 插值默认只读“项目目录”的 .env（即 infra/compose/），
# 不读仓库根 .env，导致根 .env 里的密钥在容器里变成空串。显式把根 .env 交给
# compose 做插值；文件不存在时不设置，行为与之前一致。
COMPOSE_ENV_FILE := $(wildcard $(CURDIR)/.env)
ifneq ($(COMPOSE_ENV_FILE),)
export COMPOSE_ENV_FILES := $(COMPOSE_ENV_FILE)
endif

CELERY_POOL ?= prefork
RAG_DATASET ?= ../../evaluation/rag/sample_queries.jsonl
CLAIM_DATASET ?= ../../evaluation/claims/sample_claims.jsonl
CLAIM_PROVIDER ?= local
INFRA_API_URL ?= http://127.0.0.1:8000
SEED_API_URL ?= http://127.0.0.1:8000
E2E_ARGS ?=
LOAD_TEST_CONCURRENCY ?= 50
LOAD_TEST_DURATION ?= 60
LOAD_TEST_ARGS ?=

.PHONY: install test smoke load-test infra-acceptance mock-acceptance business-sandbox-acceptance acceptance-corpus acceptance-seed acceptance-final seed-demo lint typecheck format api web build worker beat rag-eval claim-eval compose-up compose-down stack-up stack-down stack-smoke preflight migrate-check db-backup db-restore observability-up observability-down e2e-web e2e-web-docker

install:
	cd apps/api && uv sync --all-groups
	cd apps/web && pnpm install --store-dir .pnpm-store

test:
	cd apps/api && uv run $(UV_RUN_FLAGS) pytest -q

smoke:
	cd apps/api && uv run $(UV_RUN_FLAGS) python scripts/smoke_closed_loop.py

load-test:
	cd apps/api && uv run $(UV_RUN_FLAGS) python ../../scripts/load_test.py \
		--concurrency $(LOAD_TEST_CONCURRENCY) \
		--duration $(LOAD_TEST_DURATION) $(LOAD_TEST_ARGS)

infra-acceptance:
	cd apps/api && uv run $(UV_RUN_FLAGS) python scripts/acceptance_real_infra.py $(INFRA_API_URL)

mock-acceptance:
	docker compose -f infra/compose/docker-compose.yml --profile app up -d mock-business
	docker compose -f infra/compose/docker-compose.yml exec -T api python scripts/acceptance_mock_systems.py http://mock-business:8090

business-sandbox-acceptance:
	cd apps/api && .venv/bin/python scripts/seed_demo_data.py $(INFRA_API_URL)
	cd apps/api && .venv/bin/python scripts/acceptance_business_sandbox.py $(INFRA_API_URL)

acceptance-corpus:
	cd apps/api && .venv/bin/python scripts/prepare_acceptance_corpus.py ../../outputs/acceptance/corpus

acceptance-seed:
	cd apps/api && .venv/bin/python scripts/prepare_acceptance_corpus.py ../../outputs/acceptance/corpus
	./scripts/sync_acceptance_corpus.sh
	docker compose -f infra/compose/docker-compose.yml exec -T api python scripts/seed_acceptance_corpus.py http://127.0.0.1:8000 /tmp/acceptance-corpus

acceptance-final:
	./scripts/acceptance_final.sh

seed-demo:
	cd apps/api && uv run $(UV_RUN_FLAGS) python scripts/seed_demo_data.py $(SEED_API_URL)

lint:
	cd apps/api && uv run $(UV_RUN_FLAGS) ruff check .
	cd apps/web && ./node_modules/.bin/tsc --noEmit

typecheck:
	cd apps/api && uv run $(UV_RUN_FLAGS) mypy src

build:
	cd apps/web && ./node_modules/.bin/vite build

e2e-web:
	cd apps/web && pnpm test:e2e

e2e-web-docker:
	docker compose -f infra/compose/docker-compose.yml --profile app --profile test run --rm e2e npx playwright test $(E2E_ARGS)

format:
	cd apps/api && uv run $(UV_RUN_FLAGS) ruff format .

api:
	cd apps/api && uv run $(UV_RUN_FLAGS) uvicorn ticket_agent.main:app --reload --port 8000

web:
	cd apps/web && ./node_modules/.bin/vite --host 127.0.0.1

worker:
	cd apps/api && uv run $(UV_RUN_FLAGS) celery -A ticket_agent.workers.celery_app:celery_app worker --loglevel=INFO --pool=$(CELERY_POOL)

beat:
	cd apps/api && uv run $(UV_RUN_FLAGS) celery -A ticket_agent.workers.celery_app:celery_app beat --loglevel=INFO

rag-eval:
	cd apps/api && uv run $(UV_RUN_FLAGS) python scripts/prepare_dev_db.py
	cd apps/api && uv run $(UV_RUN_FLAGS) alembic upgrade head
	cd apps/api && uv run $(UV_RUN_FLAGS) python scripts/evaluate_rag.py $(RAG_DATASET) --top-k 5

claim-eval:
	cd apps/api && uv run $(UV_RUN_FLAGS) python scripts/evaluate_claim_judge.py $(CLAIM_DATASET) --provider $(CLAIM_PROVIDER)

compose-up:
	docker compose -f infra/compose/docker-compose.yml up -d

compose-down:
	docker compose -f infra/compose/docker-compose.yml down

stack-up:
	$(MAKE) build
	docker compose -f infra/compose/docker-compose.yml --profile app up -d --build

stack-down:
	docker compose -f infra/compose/docker-compose.yml --profile app stop web api worker beat migrate

stack-smoke:
	docker compose -f infra/compose/docker-compose.yml exec -T api python scripts/acceptance_real_infra.py http://127.0.0.1:8000

preflight:
	./scripts/preflight_check.sh $(PREFLIGHT_ARGS)

migrate-check:
	docker compose -f infra/compose/docker-compose.yml exec -T api python scripts/migration_preflight.py --expect-head

db-backup:
	./scripts/db_backup.sh

db-restore:
	./scripts/db_restore.sh $(DUMP) $(RESTORE_CONFIRM)

observability-up:
	docker compose -f infra/compose/docker-compose.yml --profile observability up -d prometheus grafana

observability-down:
	docker compose -f infra/compose/docker-compose.yml --profile observability stop prometheus grafana


