UV_CACHE_DIR := $(CURDIR)/.cache/uv
UV_RUN_FLAGS ?= --offline
export UV_CACHE_DIR

CELERY_POOL ?= prefork
RAG_DATASET ?= ../../evaluation/rag/sample_queries.jsonl
CLAIM_DATASET ?= ../../evaluation/claims/sample_claims.jsonl
CLAIM_PROVIDER ?= local
INFRA_API_URL ?= http://127.0.0.1:8000
SEED_API_URL ?= http://127.0.0.1:8000
E2E_ARGS ?=

.PHONY: install test smoke infra-acceptance mock-acceptance business-sandbox-acceptance acceptance-corpus acceptance-seed acceptance-final seed-demo lint typecheck format api web build worker beat rag-eval claim-eval compose-up compose-down stack-up stack-down stack-smoke observability-up observability-down e2e-web e2e-web-docker

install:
	cd apps/api && uv sync --all-groups
	cd apps/web && pnpm install --store-dir .pnpm-store

test:
	cd apps/api && uv run $(UV_RUN_FLAGS) pytest -q

smoke:
	cd apps/api && uv run $(UV_RUN_FLAGS) python scripts/smoke_closed_loop.py

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

observability-up:
	docker compose -f infra/compose/docker-compose.yml --profile observability up -d prometheus grafana

observability-down:
	docker compose -f infra/compose/docker-compose.yml --profile observability stop prometheus grafana


