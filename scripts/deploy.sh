#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
GEMINI_API_KEY="${GEMINI_API_KEY:?Set GEMINI_API_KEY}"
SERVICE_NAME="souschef-live"
REGION="${REGION:-us-central1}"
MODEL="${MODEL:-gemini-2.5-flash-native-audio-latest}"

echo "Building frontend..."
npm run build

echo "Enabling required services..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project "$PROJECT_ID"

echo "Deploying Cloud Run service..."
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --allow-unauthenticated \
  --session-affinity \
  --timeout 3600 \
  --min-instances 1 \
  --max-instances 4 \
  --concurrency 1 \
  --cpu 2 \
  --memory 1Gi \
  --set-env-vars GEMINI_API_KEY="$GEMINI_API_KEY" \
  --set-env-vars MODEL="$MODEL" \
  --set-env-vars SESSION_IDLE_TTL="300" \
  --set-env-vars SESSION_MAX_AGE="3600" \
  --set-env-vars DEV_MODE="false"

echo ""
echo "Deployed! Getting service URL..."
gcloud run services describe "$SERVICE_NAME" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --format 'value(status.url)'
