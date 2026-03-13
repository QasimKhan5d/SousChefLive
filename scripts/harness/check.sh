#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "=== Static Checks ==="

echo "→ Python import check..."
python -c "
from server.observability import emit, get_run_id
from server.session_store import SessionContext, get_or_create_session
from server.prompts import SYSTEM_INSTRUCTION, build_tool_declarations
from server.tools import set_timer, update_cooking_step, get_cooking_state, update_recipe
from server.gemini_live import GeminiLive
from harness.fakes.fake_genai import FakeGenaiClient, FakeLiveSession
print('  All imports OK')
"

echo "→ Frontend build check..."
npx vite build 2>&1 | tail -3

echo "→ pip check..."
pip check 2>&1 | tail -3 || true

echo ""
echo "=== Static checks PASSED ==="
