.PHONY: up down build logs test migrate shell-backend shell-db

## Start all services
up:
	docker compose up -d

## Stop all services
down:
	docker compose down

## Build images
build:
	docker compose build

## View logs
logs:
	docker compose logs -f

## Run all tests
test:
	docker compose exec backend pytest tests/ -v --cov=app --cov-report=term-missing

## Run migrations
migrate:
	docker compose exec backend alembic upgrade head

## Create new migration
migration:
	docker compose exec backend alembic revision --autogenerate -m "$(MSG)"

## Shell into backend
shell-backend:
	docker compose exec backend bash

## Shell into database
shell-db:
	docker compose exec postgres psql -U hcd_user hcd_db

## Install frontend dependencies
frontend-install:
	cd frontend && npm install

## Start frontend dev server
frontend-dev:
	cd frontend && npm run dev

## Type check frontend
frontend-typecheck:
	cd frontend && npm run type-check

## Format backend code
format:
	docker compose exec backend black app/ tests/
	docker compose exec backend isort app/ tests/

## Lint backend
lint:
	docker compose exec backend flake8 app/ tests/
	docker compose exec backend mypy app/

## Check Celery queues
celery-inspect:
	docker compose exec celery_worker celery -A app.tasks.celery_app inspect active

## Purge Celery queues (DANGER)
celery-purge:
	docker compose exec celery_worker celery -A app.tasks.celery_app purge

## Create superuser
create-admin:
	docker compose exec backend python scripts/create_admin.py

## Backup database
backup-db:
	docker compose exec postgres pg_dump -U hcd_user hcd_db > backup_$$(date +%Y%m%d_%H%M%S).sql

## Show running services
status:
	docker compose ps
