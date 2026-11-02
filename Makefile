COMPOSE := docker compose -f infra/docker-compose.yml
RUN := uv run

.PHONY: help install up up-all down reset migrate seed-dev api test test-unit test-int test-data lint fmt check data

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

install:         ## install Python deps incl. dev + data groups (uv)
	uv sync --all-groups

up:              ## start Postgres + Redis
	$(COMPOSE) up -d --wait postgres redis

up-all:          ## start the data services and the API container
	$(COMPOSE) --profile app up -d --build --wait

down:            ## stop containers (keeps data)
	$(COMPOSE) --profile app down

reset:           ## stop containers and DELETE the local database volume
	$(COMPOSE) --profile app down -v

migrate:         ## apply database migrations
	$(RUN) alembic upgrade head

seed-dev:        ## load the small local-development dataset (idempotent)
	$(RUN) python -m infra.scripts.dev_seed

api:             ## run the API locally with reload
	$(RUN) uvicorn services.api.main:app --reload --port 8000

test: test-unit test-data test-int  ## all tests

test-unit:       ## unit tests (no Docker needed)
	$(RUN) pytest tests/unit -q

test-data:       ## data transform checks (full-dataset checks skip if raw files are absent)
	$(RUN) --group data pytest data/transforms/tests -q -rs

test-int:        ## integration tests (need `make up migrate`; skipped if Postgres is down)
	$(RUN) pytest tests/integration -q -rs

lint:            ## ruff + mypy + module-boundary contracts
	$(RUN) ruff check .
	$(RUN) ruff format --check .
	$(RUN) mypy services
	$(RUN) lint-imports

fmt:             ## auto-format
	$(RUN) ruff check . --fix
	$(RUN) ruff format .

check: lint test-unit test-data  ## what CI runs

data:            ## run all data transforms (needs raw files in data/raw, see data/inventory.md)
	$(RUN) --group data python -m data.transforms.no_shows
