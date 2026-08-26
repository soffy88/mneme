.DEFAULT_GOAL := help

PYTHON ?= .venv/bin/python
UV ?= uv

.PHONY: help bootstrap dev test migrate seed backfill-events-dry-run backfill-events web-build pilot-readiness clean

help:
	@printf '%s\n' \
	  'make bootstrap  Install the locked Python dependencies' \
	  'make dev        Start the local Docker services' \
	  'make migrate    Apply Alembic migrations using DATABASE_URL' \
	  'make seed       Import the checked-in question bank' \
	  'make backfill-events-dry-run  Audit legacy events without writing' \
	  'make backfill-events  Run the explicitly enabled v2 event backfill' \
	  'make test       Run the repository quality gate' \
	  'make web-build  Install and build the Studio frontend' \
	  'make pilot-readiness  Check real-world validation engineering readiness' \
	  'make clean      Remove local Python/test caches'

bootstrap:
	$(UV) sync --locked

dev:
	docker compose up -d

migrate:
	$(UV) run alembic upgrade head

seed:
	$(UV) run python -m scripts.seed_question_bank

backfill-events-dry-run:
	$(PYTHON) scripts/backfill_learning_events.py --dry-run

backfill-events:
	$(PYTHON) scripts/backfill_learning_events.py

test:
	./scripts/check.sh

web-build:
	npm --prefix apps/mneme-studio ci
	npm --prefix apps/mneme-studio run build

pilot-readiness:
	$(UV) run python scripts/pilot_readiness.py

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
