#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "=== Deploy Smoke Harness (Cloud Run) ==="
echo ""

DEPLOY_URL="${DEPLOY_URL:-}"
if [ -z "$DEPLOY_URL" ]; then
  echo "Discovering Cloud Run URL..."
  DEPLOY_URL=$(gcloud run services describe souschef-live \
    --region=europe-west1 \
    --format='value(status.url)' 2>/dev/null || true)
fi

if [ -z "$DEPLOY_URL" ]; then
  echo "ERROR: Could not find deployed URL."
  echo "  Set DEPLOY_URL=https://your-cloudrun-url or deploy first."
  exit 1
fi

echo "Target: $DEPLOY_URL"
echo ""

RUN_ID="run_$(date +%Y%m%d_%H%M%S)_deploy"
ARTIFACT_DIR="artifacts/harness/$RUN_ID"
mkdir -p "$ARTIFACT_DIR"

PASSED=0
FAILED=0

check() {
  local name="$1"
  local result="$2"
  if [ "$result" = "pass" ]; then
    echo "  ✓ $name"
    PASSED=$((PASSED + 1))
  else
    echo "  ✗ $name"
    FAILED=$((FAILED + 1))
  fi
}

echo "→ Health endpoint..."
HEALTH=$(curl -s -o /dev/null -w '%{http_code}' "$DEPLOY_URL/api/health" 2>/dev/null || echo "000")
if [ "$HEALTH" = "200" ]; then
  check "Health endpoint returns 200" "pass"
  curl -s "$DEPLOY_URL/api/health" > "$ARTIFACT_DIR/health.json"
else
  check "Health endpoint returns 200 (got $HEALTH)" "fail"
fi

echo "→ Frontend served..."
INDEX=$(curl -s -o /dev/null -w '%{http_code}' "$DEPLOY_URL/" 2>/dev/null || echo "000")
if [ "$INDEX" = "200" ]; then
  check "Frontend index.html served" "pass"
else
  check "Frontend index.html served (got $INDEX)" "fail"
fi

echo "→ WebSocket upgrade check..."
WS_URL="${DEPLOY_URL/https:/wss:}/ws?session_id=deploy_smoke"
WS_CHECK=$(curl -s -o /dev/null -w '%{http_code}' \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGVzdA==" \
  "$DEPLOY_URL/ws?session_id=deploy_smoke" 2>/dev/null || echo "000")
if [ "$WS_CHECK" = "101" ]; then
  check "WebSocket upgrade accepted" "pass"
else
  check "WebSocket upgrade (got $WS_CHECK, expected 101; may need wscat)" "fail"
fi

echo ""
echo "Results: $PASSED passed, $FAILED failed"

cat > "$ARTIFACT_DIR/deploy_smoke_report.json" << EOF
{
  "run_id": "$RUN_ID",
  "tier": "deploy",
  "deploy_url": "$DEPLOY_URL",
  "passed": $PASSED,
  "failed": $FAILED,
  "checks": {
    "health": "$HEALTH",
    "index": "$INDEX",
    "websocket": "$WS_CHECK"
  }
}
EOF

echo "Artifacts: $ARTIFACT_DIR"

if [ $FAILED -gt 0 ]; then
  echo ""
  echo "=== Deploy smoke FAILED ==="
  exit 1
else
  echo ""
  echo "=== Deploy smoke PASSED ==="
  exit 0
fi
