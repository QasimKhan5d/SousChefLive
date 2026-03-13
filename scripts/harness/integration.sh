#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."

RUN_ID="run_$(date +%Y%m%d_%H%M%S)_integ"
ARTIFACT_DIR="artifacts/harness/$RUN_ID"
mkdir -p "$ARTIFACT_DIR"

echo "=== Integration Tests ==="
export LIVE_BACKEND_MODE=fake
export GEMINI_API_KEY=test-key
export HARNESS_ARTIFACT_DIR="$ARTIFACT_DIR"

python -m pytest server/tests/integration/ -v --tb=short \
  --junitxml="$ARTIFACT_DIR/integration_results.xml" 2>&1 | tee "$ARTIFACT_DIR/integration_output.log"
RESULT=${PIPESTATUS[0]}

echo ""
if [ $RESULT -eq 0 ]; then
  echo "=== Integration tests PASSED ==="
else
  echo "=== Integration tests FAILED ==="
fi

echo "Artifacts: $ARTIFACT_DIR"
exit $RESULT
