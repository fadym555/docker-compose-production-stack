.PHONY: up down test logs ps backup-now

up:
	@test -f .env || cp .env.example .env
	docker compose up -d --build --wait

down:
	docker compose down

test:
	set -a; . ./.env; set +a; bash tests/test_stack.sh

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

backup-now:
	docker compose restart backup
