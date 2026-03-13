#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."

RUN_ID="run_$(date +%Y%m%d_%H%M%S)_unit"
ARTIFACT_DIR="artifacts/harness/$RUN_ID"
mkdir -p "$ARTIFACT_DIR"

echo "=== Unit Tests ==="
export HARNESS_ARTIFACT_DIR="$ARTIFACT_DIR"

python -m pytest server/tests/unit/ -v --tb=short \
  --junitxml="$ARTIFACT_DIR/unit_results.xml" 2>&1 | tee "$ARTIFACT_DIR/unit_output.log"
RESULT=${PIPESTATUS[0]}

echo ""
if [ $RESULT -eq 0 ]; then
  echo "=== Unit tests PASSED ==="
else
  echo "=== Unit tests FAILED ==="
fi

echo "Artifacts: $ARTIFACT_DIR"
exit $RESULT
