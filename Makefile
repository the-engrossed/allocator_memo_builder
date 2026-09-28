.PHONY: up down test logs

up:
	docker compose up --build

down:
	docker compose down

test:
	docker compose run --no-deps --rm api pytest -q

logs:
	docker compose logs -f api web
