# docker-compose-production-stack

[![CI](https://github.com/fadym555/docker-compose-production-stack/actions/workflows/ci.yml/badge.svg)](https://github.com/fadym555/docker-compose-production-stack/actions/workflows/ci.yml)

A full application stack in one Compose file, set up the way I'd run it for a client on a single server: reverse proxy in front, app and worker behind it, database and cache on a private network, metrics and dashboards out of the box, and nightly backups that are actually tested.

## What's in it

| Service | Image | Job |
|---|---|---|
| proxy | nginx 1.27 | Public entry point. Rate limiting, security headers, hides internal endpoints |
| api | built from ./api | FastAPI app. Postgres for data, Redis for cache and job queue, Prometheus metrics |
| worker | built from ./api | Pulls jobs off the Redis queue, graceful shutdown, its own metrics |
| db | postgres 17 | Persistent volume, healthcheck, only on the private network |
| redis | redis 7 | AOF persistence, memory cap with LRU eviction |
| backup | postgres 17 | pg_dump on a schedule with rotation |
| prometheus | prometheus 3 | Scrapes api and worker, alert rules for downtime, errors, latency, failed jobs |
| grafana | grafana 11 | Datasource and dashboard provisioned from code |

## Design choices

- **Two networks.** `backend` is internal, so Postgres and Redis can't be reached from outside even by mistake.
- **Healthchecks everywhere** and `depends_on: service_healthy`, so services start in the right order and `docker compose up --wait` only returns once everything is really ready.
- **Resource limits and log rotation** so one noisy container can't take the box down or fill the disk.
- **Non-root, multi-stage image** for the app.
- **Ops ports bound to 127.0.0.1.** Prometheus and Grafana are reachable over SSH tunnel or VPN, not the open internet.

## What CI checks on every push

1. hadolint on the Dockerfile, shellcheck on the scripts, `docker compose config`, `promtool` on the Prometheus config and alert rules.
2. Trivy scan of the app image, failing on critical CVEs.
3. Brings up all 8 services and runs [tests/test_stack.sh](tests/test_stack.sh): proxy, API, worker job processing, Redis caching, Prometheus targets, alert rules, Grafana dashboard.
4. Restarts the API and confirms data is still there.
5. Takes a fresh backup, restores it into a new database and checks the rows came back.

## Run it

```bash
cp .env.example .env   # then change the passwords
make up                # build and start, waits until healthy
make test              # run the end-to-end checks
```

- App: http://localhost:8080
- Grafana: http://localhost:3000 (dashboard: Stack > Stack overview)
- Prometheus: http://localhost:9090

## Backups

The `backup` service dumps the database once on start and then every `BACKUP_INTERVAL_SECONDS` (default 24h), keeping the newest `BACKUP_KEEP` files. To restore:

```bash
docker compose exec -T backup sh -c 'gunzip -c /backups/<file>.sql.gz' | docker compose exec -T db psql -U app -d app
```
