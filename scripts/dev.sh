#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Load .env
if [ -f .env ]; then
  set -a; source .env; set +a
fi

cleanup() {
  echo "Shutting down..."
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
  wait $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting backend (uvicorn on :8080)..."
python -m uvicorn server.main:app --host 0.0.0.0 --port 8080 --reload &
BACKEND_PID=$!

echo "Starting frontend (vite dev on :5173)..."
npx vite --host &
FRONTEND_PID=$!

echo ""
echo "  Frontend: http://localhost:5173"
echo "  Backend:  http://localhost:8080"
echo "  Press Ctrl+C to stop"
echo ""

wait
