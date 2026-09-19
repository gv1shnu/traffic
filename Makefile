.PHONY: install models fixtures test lint format build evaluate simulate previews up down
install:
	uv sync --extra dev --extra vision
	npm --prefix apps/web ci
models:
	uv run python scripts/download_models.py --ocr
fixtures:
	uv run python scripts/generate_fixtures.py
test:
	uv run pytest -q
	npm --prefix apps/web test
lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy apps/api apps/worker packages
	npm --prefix apps/web run lint
format:
	uv run ruff format .
	apps/web/node_modules/.bin/prettier --write 'apps/web/src/**/*.{ts,tsx,css}'
build:
	npm --prefix apps/web run build
evaluate:
	uv run python scripts/evaluate.py
simulate:
	uv run python scripts/simulate.py
previews:
	uv run python scripts/render_previews.py
up:
	docker compose up --build -d
down:
	docker compose down
