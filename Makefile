.PHONY: up down test logs

TEST_DATABASE_URL ?= postgresql+psycopg://allocator:allocator@postgres:5432/allocator_test

up:
	docker compose up --build

down:
	docker compose down

test:
	docker compose run --rm -e TEST_DATABASE_URL=$(TEST_DATABASE_URL) api pytest -q

logs:
	docker compose logs -f api web
