#!/usr/bin/env bash
# End-to-end smoke for the exception sensor (ADR-0146).
#
# Not run in CI — it needs Docker and pulls two images. It exists because the
# unit, config and scenario layers all passed while the loop had never actually
# been run once, and running it found two real defects: compose interpolating
# every service's variables (so a local-only start demanded TLS certs), and the
# proxy's upstream pointing at Bugsink's port instead of the dashboard's.
#
# What it proves, in order:
#   1. a real exception reaches a real Bugsink through the real adapter
#   2. Bugsink groups it into an issue
#   3. the nginx lane rewrites, pins ?source=, and injects the operator bearer
#   4. a client CANNOT choose its own provenance
#   5. everything else 404s
#
# Usage:  scripts/bugsink_e2e_smoke.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
WORK="$(mktemp -d)"
ENVF="$WORK/.env.e2e"
CERTS="$ROOT/.e2e-certs"
COMPOSE=(docker compose --env-file "$ENVF" -f docker-compose.bugsink.yml -f docker-compose.intake-proxy.yml)

cleanup() {
  "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
  [ -n "${ECHO_PID:-}" ] && kill "$ECHO_PID" 2>/dev/null || true
  rm -rf "$WORK" "$CERTS"
}
trap cleanup EXIT

OP_TOKEN="hfop_e2e_$(openssl rand -hex 16)"
EXC_TOKEN="$(openssl rand -hex 16)"
REP_TOKEN="$(openssl rand -hex 16)"

mkdir -p "$CERTS"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$CERTS/privkey.pem" \
  -out "$CERTS/fullchain.pem" -days 1 -subj "/CN=localhost" >/dev/null 2>&1

cat > "$ENVF" <<ENV
BUGSINK_SECRET_KEY=e2e-only-not-a-real-secret-key-padded-to-fifty-chars-ab
BUGSINK_SUPERUSER=e2e@example.com:e2epassword
BUGSINK_DB_PASSWORD=e2e-db-password
BUGSINK_PORT=8000
BUGSINK_BASE_URL=http://localhost:8000
HF_TLS_CERT_DIR=$CERTS
HF_EXCEPTION_PATH_TOKEN=$EXC_TOKEN
HF_REPORT_PATH_TOKEN=$REP_TOKEN
HYDRAFLOW_OPERATOR_TOKEN=$OP_TOKEN
ENV

echo "==> starting Bugsink"
"${COMPOSE[@]}" up -d bugsink-db bugsink >/dev/null
for _ in $(seq 1 40); do
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose --env-file "$ENVF" -f docker-compose.bugsink.yml ps -q bugsink)" 2>/dev/null)" = "healthy" ] && break
  sleep 5
done

echo "==> creating a team, a project, and reading its DSN"
J="$WORK/cookies"
login_csrf=$(curl -s -c "$J" http://localhost:8000/accounts/login/ | grep -oE 'name="csrfmiddlewaretoken" value="[^"]+"' | head -1 | sed 's/.*value="//;s/"//')
curl -s -b "$J" -c "$J" -o /dev/null -X POST http://localhost:8000/accounts/login/ \
  -H "Referer: http://localhost:8000/accounts/login/" \
  --data-urlencode "csrfmiddlewaretoken=$login_csrf" \
  --data-urlencode "username=e2e@example.com" --data-urlencode "password=e2epassword"

t_csrf=$(curl -s -b "$J" -c "$J" http://localhost:8000/teams/new/ | grep -oE 'name="csrfmiddlewaretoken" value="[^"]+"' | head -1 | sed 's/.*value="//;s/"//')
curl -s -b "$J" -c "$J" -o /dev/null -X POST http://localhost:8000/teams/new/ \
  -H "Referer: http://localhost:8000/teams/new/" \
  --data-urlencode "csrfmiddlewaretoken=$t_csrf" --data-urlencode "name=e2e-team" --data-urlencode "visibility=99"

TEAM=$(curl -s -b "$J" http://localhost:8000/projects/new/ | grep -oE '<option value="[0-9a-f-]{36}"' | head -1 | sed 's/.*value="//;s/"//')
p_csrf=$(curl -s -b "$J" -c "$J" http://localhost:8000/projects/new/ | grep -oE 'name="csrfmiddlewaretoken" value="[^"]+"' | head -1 | sed 's/.*value="//;s/"//')
curl -s -b "$J" -c "$J" -o /dev/null -X POST http://localhost:8000/projects/new/ \
  -H "Referer: http://localhost:8000/projects/new/" \
  --data-urlencode "csrfmiddlewaretoken=$p_csrf" --data-urlencode "name=hydraflow-e2e" \
  --data-urlencode "team=$TEAM" --data-urlencode "visibility=99" \
  --data-urlencode "grouping_mechanism=bugsink-v2" --data-urlencode "retention_max_event_count=10"

DSN=$(curl -s -b "$J" http://localhost:8000/projects/1/edit/ | grep -oE "http://[A-Za-z0-9]+@localhost:8000/[0-9]+" | head -1)
[ -n "$DSN" ] || { echo "FAIL: no DSN"; exit 1; }
echo "    DSN acquired"

echo "==> 1/5 real exception through the real adapter"
PYTHONPATH=src SENTRY_DSN="$DSN" .venv/bin/python - <<'PY'
import os, sys
sys.path.insert(0, "src")
from config import Credentials
from observability.sentry_adapter import build_observability_adapter
a = build_observability_adapter(Credentials(sentry_dsn=os.environ["SENTRY_DSN"]))
assert type(a).__name__ == "SentryObservabilityAdapter", f"got {type(a).__name__}"
try:
    int("not-an-int")
except ValueError as exc:
    a.capture_exception(exc)
assert a.flush(5000) is True, "flush failed"
PY

echo "==> 2/5 Bugsink grouped it"
sleep 5
curl -s -b "$J" -L "http://localhost:8000/issues/?project=1" | grep -q "ValueError" \
  || { echo "FAIL: Bugsink did not ingest the error"; exit 1; }

echo "==> 3/5 the nginx lane rewrites, pins source, injects the bearer"
cat > "$WORK/echo.py" <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer
import json, sys
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        json.dump({"path": self.path, "auth": self.headers.get("Authorization")},
                  open(sys.argv[1], "w"))
        self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", 5555), H).serve_forever()
PY
.venv/bin/python "$WORK/echo.py" "$WORK/got.json" & ECHO_PID=$!
sleep 2
"${COMPOSE[@]}" up -d hydraflow-intake-proxy >/dev/null
sleep 4
curl -sk -o /dev/null -X POST "https://localhost:8443/exception/$EXC_TOKEN" \
  -H "Content-Type: application/json" -d '{"id":"e2e","title":"ValueError: x"}'
python3 - "$WORK/got.json" "$OP_TOKEN" <<'PY'
import json, sys
got = json.load(open(sys.argv[1]))
assert got["path"] == "/api/issues/intake?source=bugsink", got["path"]
assert got["auth"] == f"Bearer {sys.argv[2]}", "bearer not injected"
PY

echo "==> 4/5 a client cannot choose its own provenance"
curl -sk -o /dev/null -X POST "https://localhost:8443/exception/$EXC_TOKEN?source=ui&admin=1" \
  -H "Content-Type: application/json" -d '{"id":"e2e2"}'
python3 - "$WORK/got.json" <<'PY'
import json, sys
got = json.load(open(sys.argv[1]))
assert got["path"] == "/api/issues/intake?source=bugsink", \
    f"client overrode the pinned source: {got['path']}"
PY

echo "==> 5/5 everything else is closed"
for probe in "/api/issues/intake" "/exception/wrong-token"; do
  code=$(curl -sk -o /dev/null -w '%{http_code}' -X POST "https://localhost:8443$probe" -d '{}')
  [ "$code" = "404" ] || { echo "FAIL: $probe returned $code, expected 404"; exit 1; }
done
code=$(curl -sk -o /dev/null -w '%{http_code}' "https://localhost:8443/exception/$EXC_TOKEN")
[ "$code" = "403" ] || { echo "FAIL: GET on the lane returned $code, expected 403"; exit 1; }

echo
echo "PASS — the sensor loop works end to end."
