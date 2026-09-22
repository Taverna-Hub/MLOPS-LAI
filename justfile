default:
    @just --list

install:
    uv sync --extra dev

run:
    uv run uvicorn src.app:app --host 0.0.0.0 --port 8000

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
