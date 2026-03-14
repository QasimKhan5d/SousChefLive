# SousChef Live — Deployment Proof Plan

This document specifies what to capture for the separate Google Cloud
deployment proof recording required by the hackathon.

---

## Required Artifacts

### 1. Cloud Run Console Screenshot
- Service: `souschef-live`
- Region: `europe-west1`
- Status: green / serving
- Capture: service overview page showing URL, revision, traffic

### 2. Service Configuration
- Min instances: 1
- Max instances: 4
- Session affinity: enabled
- Memory: 1Gi
- CPU: 2
- Timeout: 3600s

### 3. Environment Variables (Masked)
- Show variable names: `GEMINI_API_KEY`, `MODEL`, `SESSION_TIME_LIMIT`, `DEV_MODE`
- Mask the API key value

### 4. Live Logs
- Open Cloud Run logs explorer
- Show structured JSON logs streaming during a live session
- Highlight: `ws_connect`, `live_connect_ok`, `tool_call_completed`, `turn_complete`

### 5. Live Session on Deployed URL
- Open deployed URL on phone or browser
- Grant permissions
- Brief cooking interaction (30-60 seconds)
- Show session badge: `europe-west1 | Cloud Run`, RTT, session ID

### 6. Architecture Diagram
- Include in repo: `docs/architecture-diagram.png` or reference from `docs/design.md`
- Shows: Browser ↔ Cloud Run ↔ Gemini Live API flow

---

## Recording Script

1. Open Cloud Run console → show service running
2. Click into service → show configuration + env vars
3. Open Logs Explorer → filter by service
4. Open deployed URL in new tab
5. Start a cooking session → show 2-3 interactions
6. Switch back to Logs → show events flowing
7. Show session badge in app

Total target: 2-3 minutes.

---

## Automated Validation

Run before recording:

```bash
./scripts/harness/deploy-smoke.sh
```

This verifies health endpoint, frontend serving, and WebSocket upgrade
on the deployed Cloud Run instance.
