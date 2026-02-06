.PHONY: install dev test lint docker-build docker-up

install:
	pip install -r requirements.txt

dev:
	uvicorn main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest

lint:
	ruff check . --fix && mypy .

docker-build:
	docker build -t ns-app-template .

docker-up:
	docker compose up --build -d
