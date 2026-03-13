#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."

RUN_LIVE=false
RUN_DEPLOY=false
RUN_SYSTEM=false

for arg in "$@"; do
  case $arg in
    --live) RUN_LIVE=true ;;
    --deploy) RUN_DEPLOY=true ;;
    --system) RUN_SYSTEM=true ;;
    --all) RUN_LIVE=true; RUN_DEPLOY=true; RUN_SYSTEM=true ;;
  esac
done

echo "========================================="
echo "  SousChef Live — Full Harness Run"
echo "========================================="
echo ""

echo "──── Tier: static ────"
./scripts/harness/check.sh
echo ""

echo "──── Tier: unit (backend) ────"
./scripts/harness/unit.sh
echo ""

echo "──── Tier: unit (frontend) ────"
npx vitest run --reporter=verbose 2>&1 || {
  echo "Frontend unit tests failed."
  exit 1
}
echo ""

echo "──── Tier: integration ────"
./scripts/harness/integration.sh
echo ""

if [ "$RUN_SYSTEM" = true ]; then
  echo "──── Tier: system ────"
  ./scripts/harness/system.sh
  echo ""
fi

if [ "$RUN_LIVE" = true ]; then
  echo "──── Tier: live ────"
  ./scripts/harness/live.sh
  echo ""
fi

if [ "$RUN_DEPLOY" = true ]; then
  echo "──── Tier: deploy ────"
  ./scripts/harness/deploy-smoke.sh
  echo ""
fi

echo "========================================="
echo "  All harness tiers PASSED"
echo "========================================="
