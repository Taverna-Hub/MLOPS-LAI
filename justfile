default:
    @just --list

install:
    uv sync --extra dev

run:
    uv run uvicorn src.app:app --host 0.0.0.0 --port 8000

test:
    uv run python -m unittest discover -s tests -v

load:
    uv run python -m monitoring.generate_load

report:
    uv run python -m monitoring.report --load-results monitoring/generated/load_results.json

lint:
    uv run ruff check .

format:
    uv run ruff format .

docker-build:
    docker compose build

docker-up:
    docker compose up -d

docker-down:
    docker compose down
