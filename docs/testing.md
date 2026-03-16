# Testing Strategy for SousChef Live

This document defines how to comprehensively test SousChef Live at every level. It exists so that any agent (human or AI) can follow it to verify the app is working correctly before a demo or release.

**Core principle**: Simple pass/fail assertions are not enough. Every test tier must also produce human-readable output that can be semantically inspected — did the agent say the right thing? Did the primer contain the right facts? Did the timer actually count down? Did the UI transition look correct?

---

## Testing Tiers

### Tier 1: Unit Tests (fast, local, no network)

**What they test**: Individual modules in isolation — data models, memory, session store, tools, prompts.

**Where they live**: `server/tests/unit/`

| File | Covers |
|---|---|
| `test_memory.py` | `ConversationTurn`, `SessionMemory`, `add_turn`, `compact`, `simple_truncate`, `needs_compaction`, `estimated_tokens`, `format_for_primer`, deque maxlen, integration with `SessionContext` and `build_reconnect_primer` |
| `test_session_store.py` | `SessionContext` defaults, `touch()`, `to_state_snapshot()`, `TimerRecord` remaining/expired, `get_or_create_session`, `cancel_session_timers`, `cleanup_session_if_idle` with new idle TTL/max age, `build_reconnect_primer` with timers, step validation |
| `test_tools.py` | `set_timer` (basic + demo speed + alerts), `update_cooking_step` (valid/invalid), `update_recipe`, `get_cooking_state` |
| `test_prompts.py` | System instruction content, tool declaration count/names/params, token budget |
| `test_observability.py` | `emit()` structured event format, artifact buffer |

**How to run**:
```bash
python -m pytest server/tests/unit/ -v
```

**Semantic verification**: After running, also run the deep verification script:
```bash
python3 -c "
from server.memory import SessionMemory
from server.session_store import SessionContext, build_reconnect_primer

# Build a realistic session and print the primer
ctx = SessionContext(session_id='demo')
ctx.recipe_name = 'Garlic Butter Chicken Thighs'
ctx.current_step = 'sear_side_1'
ctx.memory.add_turn('cook', 'Should I flip now?')
ctx.memory.add_turn('chef', 'Yes, flip it.')
ctx.memory.rolling_summary = 'Cook started with chicken, garlic, butter. Seasoned and began searing.'

primer = build_reconnect_primer(ctx)
print(primer)
print(f'Length: {len(primer)} chars')
snap = ctx.to_state_snapshot()
import json
print(json.dumps(snap, indent=2, default=str))
"
```

**What to look for**:
- Primer reads like natural context that a new Gemini session could use to resume coaching
- State snapshot includes all fields the browser needs (type, session_id, recipe, step, timers, transcript)
- Compaction reduces turns while preserving summary and facts
- Token estimates are reasonable (not wildly over or under)

---

### Tier 2: Integration Tests (local, fake Gemini backend)

**What they test**: Full FastAPI WebSocket endpoint behavior with `LIVE_BACKEND_MODE=fake`. Tests the complete request lifecycle: connect → setup → events → disconnect, without hitting the real Gemini API.

**Where they live**: `server/tests/integration/test_websocket.py`

| Test | What it verifies |
|---|---|
| `test_health` | `/api/health` returns 200 with model info |
| `test_ws_connect_disconnect` | WebSocket accepts and handles disconnect cleanly |
| `test_ws_binary_frame` | Binary audio frames are accepted |
| `test_ws_json_image_frame` | JSON image frames are routed to video queue |
| `test_ws_json_text_frame` | JSON text frames are routed to text queue |
| `test_ws_control_demo_speed` | Control frames are parsed without error |
| `test_reconnect_reuses_session` | Same session_id reconnects to existing `SessionContext` |
| `test_recipe_start_scenario` | Scripted tool calls produce correct events |
| `test_set_timer_scenario` | Timer tool call emits correct state_update |
| `test_reconnect_with_state_sends_primer` | Reconnect with existing state emits `reconnect_primer_sent` |
| `test_reconnect_sends_state_hydration` | Reconnect sends full state snapshot as first event (type, recipe, step, transcript) |
| `test_transient_disconnect_keeps_session` | Non-explicit disconnect emits `session_kept_alive`, keeps session in store |
| `test_graceful_end_session_cleans_up` | `end_session` control emits `session_ended`, removes from store |
| `test_timer_survives_disconnect` | Timer set before disconnect still exists with correct remaining time after reconnect |

**How to run**:
```bash
python -m pytest server/tests/integration/test_websocket.py -v -s
```

**Semantic verification**: Run with `-s` to see structured observability events. Check:
- `state_hydration_sent` event fires before the primer on reconnect
- `session_kept_alive` (not `session_ended`) fires on transient disconnect
- `reconnect_primer_sent` with a `primer_length` > 0
- `live_connect_start` shows `has_handle: false` for new sessions
- `session_ended` + `timers_cancelled` fires on explicit end

---

### Tier 3: Live API Tests (network-dependent, real Gemini)

**What they test**: Real Gemini Live API connectivity, audio generation, and transcription.

**Where they live**: `tests/live/`

| File | What it tests |
|---|---|
| `test_live_smoke.py` | Direct Gemini API: connect, text input, audio response, transcription |
| `test_deployed_e2e.py` | Deployed Cloud Run service: health, frontend, WebSocket connect/setup, text turns with audio response, tool calling, transcription, graceful end session |
| `test_proactive_behavior.py` | Deployed proactive guardrails: `run_id` correlation, 45s idle silence negative control, no post-recipe chatter, safe-prep-image silence, timer milestone proactive speech |
| `test_demo_flow.py` | Multi-turn demo simulation against real Gemini |
| `test_timer_lifecycle.py` | Timer tool call and state updates via real API |
| `test_vision_scenarios.py` | Image input handling |
| `test_persona_guardrails.py` | System instruction compliance |
| `test_stress.py` | Multi-turn stability |

**How to run**:
```bash
# Smoke test (fastest, verifies Gemini API key works)
set -a && source .env && set +a && python -m pytest tests/live/test_live_smoke.py -v --timeout=30

# Deployed E2E (requires active Cloud Run deployment)
set -a && source .env && set +a && python -m pytest tests/live/test_deployed_e2e.py -v --timeout=90

# Proactive live regression pack
set -a && source .env && set +a && python -m pytest tests/live/test_proactive_behavior.py -v --timeout=180

# Full live suite (slow, may have non-deterministic failures)
set -a && source .env && set +a && python -m pytest tests/live/ -v --timeout=120
```

**Semantic verification**: After test_deployed_e2e.py, check Cloud Run logs:
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="souschef-live"' \
  --project souschef-490112 --format="value(textPayload)" --limit=30 --freshness=10m
```

Look for the complete lifecycle: `ws_connect` → `session_created` → `live_connect_start` → `live_connect_ok` → `audio_out_chunk` → `turn_complete` → `session_ended` (or `session_kept_alive`).

For proactive validation, also look for:
- `proactive_candidate_created` → `proactive_candidate_sent` for timer milestones
- zero `proactive_candidate_sent` during the 45-second idle negative-control window
- `proactive_eval_suppressed_non_issue` or no proactive events when using safe prep fixtures
- matching frontend `proactive_meta_received` / backend candidate IDs when browser tests are run

---

### Tier 4: Browser Tests (Playwright, against deployed service)

**What they test**: The actual frontend UI as rendered in a real Chromium browser. Uses fake media streams for camera/mic. Takes screenshots on failure.

**Where they live**: `tests/browser/`

| File | What it tests |
|---|---|
| `app.spec.js` | Landing page elements, feature badges, powered-by badge, health API, screen transitions, cooking screen UI elements, live indicator, connection bars, WebSocket session establishment, stop button, demo speed toggle, error banner, transcript toggle |
| `demo_flow.spec.js` | Visual verification of branding, gradient bg, feature badges, cooking screen proof signals, WebSocket badge updates, demo speed control, UI reset on stop, transcript panel, video element attributes, glassmorphism styling |
| `proactive.spec.js` | Frontend observability/debug hooks: `server_run_id_received`, `proactive_meta_received`, no unsolicited proactive UI events during silent fake-media sessions |

**How to run**:
```bash
DEPLOYED_URL=https://souschef-live-5z4a6smnda-ew.a.run.app \
  npx playwright test --config tests/browser/playwright.config.js --reporter=list
```

**Taking screenshots for manual inspection**:
```bash
DEPLOYED_URL=https://souschef-live-5z4a6smnda-ew.a.run.app \
  npx playwright test --config tests/browser/playwright.config.js \
  --reporter=html --screenshot=on
npx playwright show-report
```

**Semantic verification**: Open the HTML report. For each test, inspect the screenshot:
- Landing page: logo, tagline, feature badges, Start Cooking button with pulse, Gemini Live API badge
- Cooking screen: full-bleed video, glassmorphism chips, live indicator, signal bars, transcript panel
- Reconnecting state: spinner overlay visible, cooking UI still intact behind it

---

## Observability: White-Box Visibility

The system emits structured JSON events via `server/observability.py::emit()` at 40+ points across the codebase. Every state transition is observable.

### Event Categories

| Component | Events |
|---|---|
| `backend.server` | `ws_connect`, `setup_received`, `setup_error`, `state_hydration_sent`, `reconnect_primer_sent`, `text_in_message`, `ws_disconnect`, `receive_error`, `session_timeout`, `session_error`, `session_ended`, `session_kept_alive`, `control_applied`, `control_end_session` |
| `backend.session` | `session_created`, `session_resumed`, `timers_cancelled`, `session_cleanup` |
| `backend.bridge` | `live_connect_start` (with has_handle, retry count), `live_connect_ok`, `resumption_handle_captured`, `go_away_received`, `audio_out_chunk`, `turn_complete`, `interrupt_received`, `tool_call_received`, `tool_call_completed`, `tool_call_failed`, `upstream_resumable_disconnect`, `upstream_reconnecting`, `upstream_retries_exhausted`, `live_connect_error` |
| `backend.tools` | Timer alerts, step updates, recipe updates (via tools.py emit calls) |

### How to Access

**In tests** (most useful):
```python
from server.observability import get_artifact_buffer, clear_artifact_buffer
clear_artifact_buffer()
# ... run test code ...
events = get_artifact_buffer()
for e in events:
    print(f"{e['event_type']:30s} session={e.get('session_id','')[:12]}  {e.get('details', {})}")
```

**In Cloud Run** (production):
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="souschef-live"' \
  --project souschef-490112 --format="json" --limit=100 --freshness=10m
```

**As artifact files** (if HARNESS_ARTIFACT_DIR is set):
```python
from server.observability import flush_artifacts
flush_artifacts("/tmp/souschef-harness")
# Creates /tmp/souschef-harness/run_<id>/report.json
```

### Key Events to Check for Session Memory Feature

After implementing session memory, these events verify correctness:

1. **New session**: `session_created` → `live_connect_start(has_handle=false, retry=0)` → `live_connect_ok`
2. **Transient disconnect**: `session_kept_alive(reason=transient_disconnect)` — NOT `session_ended`
3. **Reconnect with state**: `session_resumed` → `state_hydration_sent` → `reconnect_primer_sent(primer_length=N)`
4. **Explicit end**: `control_end_session` → `timers_cancelled` → `session_ended`
5. **Gemini upstream reconnect**: `go_away_received` or `upstream_resumable_disconnect` → `upstream_reconnecting(retry=N, delay=N)` → `live_connect_start(has_handle=true)`
6. **Resumption handle**: `resumption_handle_captured` after model sends `session_resumption_update`
7. **Timeout**: `session_timeout` → session still in store until idle TTL

---

## Pre-Demo Checklist

Run this before every demo or significant deployment:

```bash
# 1. Unit tests (should take <3s)
python -m pytest server/tests/unit/ -v

# 2. Integration tests (should take <2s)
python -m pytest server/tests/integration/ -v

# 3. Build and deploy
# Judges / repository default
set -a && source .env && set +a && bash scripts/deploy.sh

# Europe demo override
set -a && source .env && set +a && REGION=europe-west1 bash scripts/deploy.sh

# 4. Health check
curl -s https://souschef-live-5z4a6smnda-ew.a.run.app/api/health | python3 -m json.tool

# 5. Live smoke test (verifies Gemini API key + audio generation)
set -a && source .env && set +a && python -m pytest tests/live/test_live_smoke.py -v --timeout=30

# 6. Deployed E2E (verifies full WebSocket lifecycle against production)
set -a && source .env && set +a && python -m pytest tests/live/test_deployed_e2e.py -v --timeout=90

# 7. Browser tests (verifies UI rendering, screenshots on failure)
DEPLOYED_URL=https://souschef-live-5z4a6smnda-ew.a.run.app \
  npx playwright test --config tests/browser/playwright.config.js --reporter=list

# 7b. Browser proactive/debug checks
DEPLOYED_URL=https://souschef-live-5z4a6smnda-ew.a.run.app \
  npx playwright test tests/browser/proactive.spec.js --config tests/browser/playwright.config.js --reporter=list

# 8. Check Cloud Run logs for any errors
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="souschef-live" AND severity>=ERROR' \
  --project souschef-490112 --limit=10 --freshness=10m --format="value(textPayload)"
```

All steps should pass with zero failures. If any browser test fails, the screenshot is saved automatically — inspect it to understand the visual state.

---

## What Still Requires Human Testing

These cannot be verified by automated tests:

1. **Real camera/microphone input** — fake media streams are synthetic
2. **Voice quality** — does Aoede sound natural? Is latency perceivable?
3. **Final real-kitchen proactivity tuning** — automated tests now cover timer milestones, silence windows, and safe-image suppression, but the last mile is whether live interruptions feel helpful rather than annoying during actual cooking
4. **Vision quality under real motion/lighting** — automated image fixtures catch regressions, but real countertops, steam, shadows, and hand motion still need human validation
5. **4-minute demo rehearsal** — timed run-through with garlic butter chicken thighs
6. **Reconnect UX feel** — correctness is automated, but the subjective smoothness of the reconnect spinner and audio continuity still benefits from human eyes/ears

---

## Architecture of Test Feedback

```
Unit Tests (server/tests/unit/)
  └── Asserts data model correctness + prints actual values for semantic check
       │
Integration Tests (server/tests/integration/)
  └── Asserts event lifecycle + observability buffer for full whitebox inspection
       │
Live API Tests (tests/live/)
  └── Asserts real Gemini responses + reads deployed WebSocket payloads
       │
Browser Tests (tests/browser/)
  └── Asserts rendered DOM + screenshots for visual inspection
       │
Cloud Run Logs (gcloud logging read)
  └── Full production observability: every event, error, state transition
       │
Human Demo
  └── Real camera, real voice, real cooking — the final validation
```

Each tier feeds the next. A failure at tier 1 is cheapest to fix. A failure found only at the human demo tier means we need better automated coverage for that scenario.
