#!/usr/bin/env bash
# smoke_test.sh — Validates every service is reachable after docker compose up
#
# Usage:
#   bash scripts/smoke_test.sh
#
# Prerequisites:
#   - docker compose up -d (all containers must be running)
#   - curl available on the host
#
# Exit codes:
#   0 — all checks passed
#   1 — one or more checks failed

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

FAILURES=0

pass()  { echo -e "  ${GREEN}✓${NC} $1"; }
fail()  { echo -e "  ${RED}✗${NC} $1"; FAILURES=$((FAILURES + 1)); }
info()  { echo -e "\n${BOLD}${YELLOW}▸${NC} ${BOLD}$1${NC}"; }

echo ""
echo -e "${BOLD}════════════════════════════════════════════${NC}"
echo -e "${BOLD}  TrustSignal AI — Infrastructure Smoke Test${NC}"
echo -e "${BOLD}════════════════════════════════════════════${NC}"
echo ""

# ── 1. Kafka broker ──────────────────────────────────────────────────────────
info "Kafka broker"
docker exec ts-broker kafka-broker-api-versions \
  --bootstrap-server localhost:9092 >/dev/null 2>&1 \
  && pass "Broker reachable at localhost:9092" \
  || fail "Broker unreachable — is ts-broker running? (docker compose up -d broker)"

# ── 2. Kafka topics ──────────────────────────────────────────────────────────
info "Kafka topics"
TOPICS=$(docker exec ts-broker \
  kafka-topics --bootstrap-server localhost:9092 --list 2>/dev/null || echo "")

echo "$TOPICS" | grep -q "interview-audio-stream" \
  && pass "interview-audio-stream  (retention=24 h)" \
  || fail "interview-audio-stream missing — did kafka-setup run?"

echo "$TOPICS" | grep -q "interview-text-stream" \
  && pass "interview-text-stream   (retention=7 d)" \
  || fail "interview-text-stream missing — did kafka-setup run?"

# ── 3. Topic retention config ────────────────────────────────────────────────
info "Kafka topic retention"
AUDIO_RETENTION=$(docker exec ts-broker \
  kafka-configs --bootstrap-server localhost:9092 \
  --describe --entity-type topics --entity-name interview-audio-stream 2>/dev/null \
  | grep "retention.ms" | grep -o "retention.ms=86400000" || echo "")
[ -n "$AUDIO_RETENTION" ] \
  && pass "interview-audio-stream retention.ms=86400000 (24 h)" \
  || fail "interview-audio-stream retention not confirmed"

TEXT_RETENTION=$(docker exec ts-broker \
  kafka-configs --bootstrap-server localhost:9092 \
  --describe --entity-type topics --entity-name interview-text-stream 2>/dev/null \
  | grep "retention.ms" | grep -o "retention.ms=604800000" || echo "")
[ -n "$TEXT_RETENTION" ] \
  && pass "interview-text-stream  retention.ms=604800000 (7 d)" \
  || fail "interview-text-stream retention not confirmed"

# ── 4. MinIO ─────────────────────────────────────────────────────────────────
info "MinIO object storage"
curl -sf http://localhost:9000/minio/health/live >/dev/null \
  && pass "MinIO health endpoint OK (localhost:9000)" \
  || fail "MinIO unreachable — is ts-minio running?"

# MinIO console
curl -sf http://localhost:9001 >/dev/null \
  && pass "MinIO console reachable (localhost:9001)" \
  || fail "MinIO console unreachable"

# ── 5. MinIO buckets (via Python minio client if available) ──────────────────
info "MinIO buckets"
if python3 -c "import minio" 2>/dev/null; then
  python3 - <<'PYEOF'
from minio import Minio
import sys
client = Minio("localhost:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
buckets = [b.name for b in client.list_buckets()]
required = ["raw-audio", "model-artifacts", "delta-tables"]
ok = True
for b in required:
    if b in buckets:
        print(f"  \033[0;32m✓\033[0m Bucket '{b}' exists")
    else:
        print(f"  \033[0;31m✗\033[0m Bucket '{b}' missing")
        ok = False
sys.exit(0 if ok else 1)
PYEOF
  STATUS=$?
  [ $STATUS -eq 0 ] || FAILURES=$((FAILURES + 1))
else
  echo -e "  ${YELLOW}⚠${NC}  minio Python package not installed — skipping bucket check"
  echo     "     Run: pip install minio  then re-run this script"
fi

# ── 6. Airflow webserver ─────────────────────────────────────────────────────
info "Airflow webserver"
curl -sf http://localhost:8080/health >/dev/null \
  && pass "Airflow webserver healthy (localhost:8080)" \
  || fail "Airflow webserver unreachable — is ts-airflow-webserver running?"

# ── 7. Spark master ──────────────────────────────────────────────────────────
info "Spark master (Delta Lake)"
curl -sf http://localhost:8090 >/dev/null \
  && pass "Spark master UI reachable (localhost:8090)" \
  || fail "Spark master unreachable — is ts-spark-master running?"

# ── Result ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}════════════════════════════════════════════${NC}"
if [ "$FAILURES" -eq 0 ]; then
  echo -e "${GREEN}${BOLD}  All checks passed. Stack is healthy.${NC}"
else
  echo -e "${RED}${BOLD}  $FAILURES check(s) failed. Review logs:${NC}"
  echo    "    docker compose logs --tail=50 <service-name>"
  exit 1
fi
echo -e "${BOLD}════════════════════════════════════════════${NC}"
echo ""
