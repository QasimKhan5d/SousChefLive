#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "=== Live Regression Harness (Real Gemini) ==="
echo ""

if [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "ERROR: GEMINI_API_KEY must be set for live regression."
  echo "  export GEMINI_API_KEY=your-key-here"
  exit 1
fi

RUN_ID="run_$(date +%Y%m%d_%H%M%S)_live"
ARTIFACT_DIR="artifacts/harness/$RUN_ID"
mkdir -p "$ARTIFACT_DIR"

echo "→ Running live regression tests..."
export LIVE_BACKEND_MODE=real
export LOG_FORMAT=json
export HARNESS_ARTIFACT_DIR="$ARTIFACT_DIR"

LIVE_TEST_DIR="tests/live"

if [ ! -d "$LIVE_TEST_DIR" ] || [ -z "$(ls -A "$LIVE_TEST_DIR"/*.py 2>/dev/null)" ]; then
  echo "  No live test files found in $LIVE_TEST_DIR."
  echo "  Creating placeholder..."
  mkdir -p "$LIVE_TEST_DIR"
fi

python -m pytest "$LIVE_TEST_DIR" -v --timeout=120 -x 2>&1 | tee "$ARTIFACT_DIR/live_output.log"
RESULT=${PIPESTATUS[0]}

echo ""
if [ $RESULT -eq 0 ]; then
  echo "=== Live regression harness PASSED ==="
else
  echo "=== Live regression harness FAILED ==="
fi

echo "Artifacts: $ARTIFACT_DIR"
exit $RESULT
