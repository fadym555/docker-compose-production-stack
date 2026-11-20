#!/usr/bin/env bash
# End-to-end checks against a running stack. Used by CI and by "make test".
set -euo pipefail

BASE="${BASE_URL:-http://localhost:8080}"
PROM="${PROM_URL:-http://localhost:9090}"
GRAFANA="${GRAFANA_URL:-http://localhost:3000}"

fail() { echo "FAIL - $1"; exit 1; }
ok() { echo "ok   - $1"; }
json() { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }

retry() {
  for _ in $(seq 1 30); do
    if "$@"; then return 0; fi
    sleep 1
  done
  return 1
}

curl -fsS "$BASE/nginx-health" >/dev/null || fail "nginx health endpoint"
ok "nginx is serving traffic"

curl -fsS "$BASE/healthz" | grep -q '"postgres":"up"' || fail "api health"
ok "api can reach postgres and redis"

code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/metrics")
[ "$code" = "404" ] || fail "metrics should not be reachable through the proxy (got $code)"
ok "metrics endpoint is not exposed publicly"

id=$(curl -fsS -X POST "$BASE/notes" -H 'content-type: application/json' -d '{"body":"shipped from the CI pipeline"}' | json '["id"]') || fail "create note"
ok "created note $id"

worker_done() { [ "$(curl -fsS "$BASE/notes/$id" | json '["word_count"]')" = "5" ]; }
retry worker_done || fail "worker did not process the queued job"
ok "worker processed the queued job"

curl -fsS "$BASE/notes/count" | grep -q '"cached":false' || fail "first count should come from postgres"
curl -fsS "$BASE/notes/count" | grep -q '"cached":true' || fail "second count should come from redis"
ok "second read is served from the redis cache"

target_up() {
  curl -fsS "$PROM/api/v1/query" --data-urlencode "query=up{job='$1'}" | python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; sys.exit(0 if r and r[0]["value"][1] == "1" else 1)'
}
for job in api worker prometheus; do
  retry target_up "$job" || fail "prometheus target $job"
  ok "prometheus is scraping $job"
done

curl -fsS "$PROM/api/v1/rules" | grep -q '"name":"TargetDown"' || fail "alert rules not loaded"
ok "alerting rules are loaded"

curl -fsS "$GRAFANA/api/health" | grep -q '"database": *"ok"' || fail "grafana health"
curl -fsS -u "admin:${GRAFANA_ADMIN_PASSWORD}" "$GRAFANA/api/dashboards/uid/stack-overview" >/dev/null || fail "dashboard not provisioned"
ok "grafana is up with the provisioned dashboard"

echo "all checks passed"
