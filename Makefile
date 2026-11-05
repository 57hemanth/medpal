COMPOSE := docker compose -f infra/docker-compose.yml
RUN := uv run

.PHONY: eval worker cost-report load-test up-boundary boundary-check help install up up-all down reset migrate api web-install web-build web-test test test-unit test-int test-data lint fmt check data seed generate

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

install:         ## install Python deps incl. dev + data groups (uv)
	uv sync --all-groups

web-install:     ## install React app dependencies
	cd web && npm install

up:              ## start Postgres + Redis
	$(COMPOSE) up -d --wait postgres redis

up-all:          ## start the data services and the API container
	$(COMPOSE) --profile app up -d --build --wait

up-boundary:     ## hybrid deployment topology: internal network, ingress + allowlisted egress only
	docker compose -f infra/docker-compose.boundary.yml up -d --build --wait

boundary-check:  ## prove the API container has no route out except the allowlisted proxy
	$(RUN) python -m infra.scripts.boundary_check

down:            ## stop containers (keeps data)
	$(COMPOSE) --profile app down

reset:           ## stop containers and DELETE the local database volume
	$(COMPOSE) --profile app down -v

migrate:         ## apply database migrations
	$(RUN) alembic upgrade head

seed:            ## RESET dev data and load the generated network (500 doctors, 480k slots) + dev identities
	$(RUN) --group data python -m infra.scripts.seed

generate:        ## regenerate the synthetic network and slot calendar (seeded, reproducible)
	$(RUN) --group data python -m data.synthetic.generate

worker:          ## run the records ingest worker locally (needs Redis: make up)
	$(RUN) arq services.worker.WorkerSettings

api:             ## run the API locally with reload
	$(RUN) uvicorn services.api.main:app --reload --port 8000

web-build:       ## type-check and build the React app
	cd web && npm run build

web-test:        ## run React unit tests
	cd web && npm test

test: test-unit test-data test-int  ## all tests

test-unit:       ## unit tests (no Docker needed)
	$(RUN) pytest tests/unit -q

test-data:       ## data transform checks (full-dataset checks skip if raw files are absent)
	$(RUN) --group data pytest data/transforms/tests data/synthetic/tests -q -rs

test-int:        ## integration tests (need `make up migrate`; skipped if Postgres is down)
	$(RUN) pytest tests/integration -q -rs

eval:            ## run the evaluation sets and enforce the release gates
	$(RUN) python -m evals.run --check

cost-report:     ## cost sheet from real traces (needs a running stack with traffic)
	$(RUN) python -m infra.scripts.cost_report

load-test:       ## 1,400 req/h then a 3x burst against a running API; p95s per endpoint
	$(RUN) python -m infra.scripts.load_test --base http://localhost:8000

lint:            ## ruff + mypy + module-boundary contracts
	$(RUN) ruff check .
	$(RUN) ruff format --check .
	$(RUN) mypy services
	$(RUN) lint-imports

fmt:             ## auto-format
	$(RUN) ruff check . --fix
	$(RUN) ruff format .

check: lint test-unit test-data web-build web-test  ## what CI runs

data:            ## run all data transforms (needs raw files in data/raw, see data/inventory.md)
	$(RUN) --group data python -m data.transforms.no_shows
