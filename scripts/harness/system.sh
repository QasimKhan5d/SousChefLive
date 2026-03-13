#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "=== System Harness (Browser Automation) ==="
echo ""
echo "Prerequisites: Playwright installed (npx playwright install chromium)"
echo ""

RUN_ID="run_$(date +%Y%m%d_%H%M%S)_sys"
ARTIFACT_DIR="artifacts/harness/$RUN_ID"
mkdir -p "$ARTIFACT_DIR/screenshots"

echo "→ Starting backend in fake mode..."
export LIVE_BACKEND_MODE=fake
export GEMINI_API_KEY=test-key
export DEV_MODE=true
export LOG_FORMAT=json
export HARNESS_ARTIFACT_DIR="$ARTIFACT_DIR"
export HARNESS_SCENARIO=system_smoke

python -m uvicorn server.main:app --host 0.0.0.0 --port 8080 --log-level warning &
BACKEND_PID=$!

echo "→ Building frontend..."
npx vite build 2>&1 | tail -3

echo "→ Waiting for backend..."
for i in $(seq 1 30); do
  if curl -s http://localhost:8080/api/health > /dev/null 2>&1; then
    echo "  Backend ready."
    break
  fi
  sleep 0.5
done

echo "→ Running Playwright tests..."
if npx playwright test frontend/tests/system/ --reporter=list 2>&1; then
  echo ""
  echo "=== System harness PASSED ==="
  RESULT=0
else
  echo ""
  echo "=== System harness FAILED ==="
  RESULT=1
fi

echo "→ Stopping backend..."
kill $BACKEND_PID 2>/dev/null || true
wait $BACKEND_PID 2>/dev/null || true

echo "Artifacts: $ARTIFACT_DIR"
exit $RESULT
