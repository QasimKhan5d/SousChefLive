# SousChef Live -- Implementation Tasks

> Generated from [design.md](design.md), [requirements.md](requirements.md), and [harness.md](harness.md).
> Each task is independently executable and produces a verifiable outcome.
> Tasks are ordered by dependency -- earlier tasks unblock later ones.
> Update each task's `Status` field in real time as implementation progresses.
> Tasks can be run individually, by phase, or end-to-end.
> Implementation must use this document and `docs/harness.md` together. Do not mark a task `done` without the required harness evidence for that task.

**Status legend**: `pending` | `in_progress` | `done` | `blocked` | `cut`

---

## Phase 1: Project Scaffold

### T-01: Initialize project structure and dependencies

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | -- |
| **Produces** | `requirements.txt`, `package.json`, `vite.config.js`, `.env.example`, `.gitignore`, `Dockerfile`, `app.json`, empty `server/` and `frontend/` dirs |
| **Design ref** | 4.2, 4.4 |

**Acceptance**:
- [ ] `pip install -r requirements.txt` succeeds (including runtime and test deps such as fastapi, uvicorn, google-genai, python-dotenv, websockets, pytest, pytest-asyncio)
- [ ] `npm install` succeeds (including Vite and any chosen frontend test runner such as Vitest)
- [ ] `.env.example` lists `GEMINI_API_KEY`, `MODEL`, `SESSION_TIME_LIMIT`, `DEV_MODE`
- [ ] `docker build .` produces a valid image (will fail at runtime until server exists -- that's fine)
- [ ] `.gitignore` covers `node_modules/`, `dist/`, `__pycache__/`, `.env`, `venv/`

---

## Phase 2: Backend Core

### T-02: Session store and data models

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-01 |
| **Produces** | `server/session_store.py` |
| **Design ref** | 1.4, 3.3 |

**Acceptance**:
- [ ] `SessionContext` and `TimerRecord` dataclasses match design spec
- [ ] `get_or_create_session(store, session_id)` returns existing or new context
- [ ] `cancel_session_timers(session)` cancels all active asyncio timer tasks
- [ ] `cleanup_session_if_idle(store, session_id)` removes stale sessions past TTL
- [ ] `build_reconnect_primer(session)` returns a text string with recipe, step, and timer state
- [ ] Unit-testable without network or API calls

### T-03: GeminiLive bridge class

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-01 |
| **Produces** | `server/gemini_live.py` |
| **Design ref** | 3.1, 3.2 |

**Acceptance**:
- [ ] `GeminiLive(api_key, model)` creates a `genai.Client(api_key=...)`
- [ ] `register_tool(func)` stores the function in `tool_mapping` by name
- [ ] `build_live_config(setup_config)` maps client setup JSON to `types.LiveConnectConfig`
- [ ] `start_session(...)` opens `client.aio.live.connect(model, config)` and runs concurrent loops:
  - audio input queue -> `session.send_realtime_input(audio blob)`
  - video input queue -> `session.send_realtime_input(image blob)`
  - text input queue -> `session.send_client_content(text)`
  - receive loop -> dispatches audio bytes, transcripts, interrupts, tool calls, turn_complete
- [ ] Tool calls are executed locally via `tool_mapping` and responses sent back with `session.send_tool_response(...)`
- [ ] Smoke test: connect to `gemini-2.5-flash-native-audio-latest`, send a text turn, receive audio bytes back

### T-04: Tool implementations

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-02 |
| **Produces** | `server/tools.py` |
| **Design ref** | 3.5 |

**Acceptance**:
- [ ] `set_timer(duration_seconds, label)`:
  - creates `TimerRecord` in session context
  - divides duration by 10 when `demo_speed=True`
  - schedules asyncio task for pre-alert (80% elapsed) and final alert (100%)
  - timer task enqueues SYSTEM text into `text_input_queue`
  - returns `{timer_id, label, effective_seconds}`
- [ ] `update_cooking_step(step_name)`:
  - validates against the step list `prep -> heat -> sear_side_1 -> flip -> sear_side_2 -> baste -> rest -> done`
  - updates `current_step` and `monitoring_status` on session context
  - returns updated state snapshot
- [ ] `get_cooking_state()`:
  - returns current step, recipe name, monitoring status, active timers with remaining seconds
- [ ] `register_session_tools(gemini, session, text_input_queue, websocket)` wires all tools and their side-effect callbacks
- [ ] Each tool emits a JSON event to the WebSocket for UI updates

### T-05: System instruction prompt

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | -- |
| **Produces** | `server/prompts.py` |
| **Design ref** | 3.4 |

**Acceptance**:
- [ ] `SYSTEM_INSTRUCTION` string covers: identity, kitchen awareness, intervention rules, tool rules, voice style
- [ ] Includes critical behavioral rules from design (smoke detection, proactive timers, no "as an AI")
- [ ] Includes demo-safe honesty rules such as describing observations without false precision
- [ ] Includes recipe suggestion -> cook mode transition behavior so the experience quickly shifts from ingredient intake to live supervision
- [ ] `build_tool_declarations()` returns the function declaration list for the four tools with proper parameter schemas
- [ ] Prompt is under 2000 tokens (keeps context budget for conversation)

---

## Phase 3: Backend Server

### T-06: FastAPI app and WebSocket endpoint

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-02, T-03, T-04, T-05 |
| **Produces** | `server/main.py` |
| **Design ref** | 3.7 |

**Acceptance**:
- [ ] `GET /` serves static frontend from `dist/`
- [ ] `WS /ws?session_id=xxx` accepts WebSocket connection
- [ ] First text frame parsed as `{"setup": {...}}`; config merged with server-side system instruction and tool declarations
- [ ] Binary frames routed to audio input queue
- [ ] JSON `image` frames routed to video input queue (base64-decoded)
- [ ] JSON `text` frames routed to text input queue
- [ ] JSON `control` frames update session (e.g. `demo_speed` toggle)
- [ ] `receive_from_client()` runs as its own asyncio task
- [ ] Session timeout enforced via `asyncio.wait_for`
- [ ] `finally` block cancels client task, cancels session timers, cleans up session
- [ ] Reconnect with existing `session_id` rebuilds Gemini session and sends reconnect primer
- [ ] Server starts with `uvicorn` on port 8080
- [ ] Smoke test: `python server/main.py` starts without errors; WebSocket connect/disconnect round-trips cleanly

---

## Phase 4: Frontend -- Audio & Media Layer

### T-07: Audio capture worklet

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-01 |
| **Produces** | `frontend/public/audio-processors/capture.worklet.js` |
| **Design ref** | 2.4 |

**Acceptance**:
- [ ] `AudioWorkletProcessor` that buffers 4096 float32 samples per chunk
- [ ] Posts message with `Float32Array` to main thread
- [ ] Designed for 16kHz sample rate AudioContext

### T-08: Audio playback worklet

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-01 |
| **Produces** | `frontend/public/audio-processors/playback.worklet.js` |
| **Design ref** | 2.4 |

**Acceptance**:
- [ ] `AudioWorkletProcessor` that plays queued PCM16 buffers at 24kHz
- [ ] Supports `interrupt` message that clears the playback queue immediately
- [ ] No clicks or pops on queue drain (fills silence when buffer empty)

### T-09: Media utilities (AudioStreamer, VideoStreamer, AudioPlayer)

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-07, T-08 |
| **Produces** | `frontend/src/lib/gemini-live/mediaUtils.js` |
| **Design ref** | 2.3, 2.4, 3.8 |

**Acceptance**:
- [ ] `AudioStreamer`: initializes 16kHz AudioContext + capture worklet, converts Float32->PCM16, calls `onAudioData(arrayBuffer)` callback
- [ ] `VideoStreamer`: captures frames from `<video>` element via canvas at 1 FPS / 640x480 / JPEG 0.8, calls `onVideoFrame(base64, mimeType)` callback
- [ ] `AudioPlayer`: initializes 24kHz AudioContext + playback worklet, `play(arrayBuffer)` enqueues data, `interrupt()` clears queue
- [ ] All three classes have `start()` and `stop()` lifecycle methods
- [ ] Works in Chrome and Safari (feature-detect AudioWorklet)

### T-10: WebSocket client (GeminiLiveClient)

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-01 |
| **Produces** | `frontend/src/lib/gemini-live/geminilive.js` |
| **Design ref** | 2.2, 3.6 |

**Acceptance**:
- [ ] `connect(sessionId)` opens WebSocket to `/ws?session_id=xxx`
- [ ] `sendSetup(config)` sends the first-message JSON payload
- [ ] `sendAudio(arrayBuffer)` sends binary frame
- [ ] `sendImage(base64, mimeType)` sends JSON image frame
- [ ] `sendText(text)` sends JSON text frame
- [ ] `sendControl(action, value)` sends JSON control frame
- [ ] `disconnect()` cleanly closes WebSocket
- [ ] Incoming binary frames routed to `onAudioData` callback
- [ ] Incoming JSON parsed and routed to typed callbacks: `onTranscriptInput`, `onTranscriptOutput`, `onToolCall`, `onStateUpdate`, `onInterrupt`, `onTurnComplete`, `onError`
- [ ] Auto-reconnect with exponential backoff on unexpected close

---

## Phase 5: Frontend -- UI Layer

### T-11: HTML shell and CSS

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-01 |
| **Produces** | `frontend/index.html`, `frontend/src/styles.css` |
| **Design ref** | 5.1-5.4 in requirements |

**Acceptance**:
- [ ] Mobile-first responsive layout
- [ ] Primary area: live camera feed (`<video>` element)
- [ ] Overlay chips: current step, monitoring status
- [ ] Timer card area (below or beside video)
- [ ] Collapsible transcript panel
- [ ] Session badge: region, RTT, session ID
- [ ] Judge-facing status evidence includes active timer/event count (for example `Timers: 1 active`)
- [ ] Start/stop button, demo speed toggle
- [ ] Permission prompt screen (camera + mic)
- [ ] Clean, modern look suitable for hackathon demo video

### T-12: State management

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-01 |
| **Produces** | `frontend/src/state.js` |
| **Design ref** | 3.8 |

**Acceptance**:
- [ ] Exports reactive `state` object with fields: `sessionId`, `isConnected`, `isAgentSpeaking`, `currentStep`, `monitoringStatus`, `timers`, `transcript`, `demoSpeed`, `sessionInfo`
- [ ] `subscribe(callback)` notifies listeners on state change
- [ ] `updateFromServerEvent(msg)` maps tool_call, state_update, transcript, interrupt events to state mutations
- [ ] Timer countdown ticks locally (1Hz) based on `started_at` and `effective_seconds`

### T-13: UI renderer and main entry point

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-09, T-10, T-11, T-12 |
| **Produces** | `frontend/src/ui.js`, `frontend/src/main.js` |
| **Design ref** | 3.6, 3.8 |

**Acceptance**:
- [ ] `main.js` orchestrates: permission request -> media init -> WebSocket connect -> setup message -> streaming loop
- [ ] `ui.js` subscribes to state and updates DOM: video feed, step chip, monitoring chip, timer cards, transcript entries, session badge
- [ ] UI surfaces the judge-facing proof elements from the demo plan: session badge, RTT, and active timer/event count
- [ ] Start button begins session; stop button disconnects cleanly
- [ ] Demo speed toggle sends control message and updates local state
- [ ] Interrupt event calls `audioPlayer.interrupt()` and updates speaking indicator
- [ ] Error events show a toast/banner with retry option
- [ ] `npm run dev` serves the app locally with hot reload via Vite

---

## Phase 6: Testing & Local Dev

### T-14: Automated unit tests

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-02, T-04, T-10, T-12 |
| **Produces** | `server/tests/`, `frontend/tests/` |
| **Design ref** | 6.2 |

**Acceptance**:
- [ ] Backend unit tests cover session store behavior: create, lookup, cleanup, reconnect primer
- [ ] Timer tests cover demo-speed compression, pre-alert scheduling, expiry scheduling, and cancellation cleanup
- [ ] State machine tests cover valid transitions, duplicate updates, and invalid skips
- [ ] Client-side parser/state tests cover transcript events, interrupt handling, state updates, and malformed JSON safety
- [ ] Test commands run successfully in CI-friendly form (for example `pytest` and `npm test`)

### T-15: Integration tests

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-06, T-10 |
| **Produces** | `server/tests/test_websocket_*.py` or equivalent integration suite |
| **Design ref** | 6.3 |

**Acceptance**:
- [ ] WebSocket round-trip test sends setup payload, one binary audio frame, and one image JSON frame
- [ ] Integration test verifies the backend routes audio/video into the correct queues
- [ ] Tool execution test verifies `set_timer()`, `update_cooking_step()`, and `get_cooking_state()` update state and emit UI events
- [ ] Reconnect test verifies reconnect with same `session_id` rebuilds the Gemini session and sends reconnect primer text
- [ ] Disconnect test verifies session tasks and timer tasks are cleaned up

### T-16: Dev server script

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-06, T-13 |
| **Produces** | `scripts/dev.sh` |
| **Design ref** | -- |

**Acceptance**:
- [ ] Starts Vite dev server for frontend (with proxy to backend WebSocket)
- [ ] Starts uvicorn for backend with reload
- [ ] Single `./scripts/dev.sh` command launches both
- [ ] `.env` loaded automatically by both processes
- [ ] Ctrl+C cleanly kills both

### T-17: End-to-end local smoke test

| Field | Value |
|-------|-------|
| **Status** | `done (harness-validated)` |
| **Depends on** | T-14, T-15, T-16 |
| **Produces** | verified working local system |
| **Design ref** | 6.4, demo.md must-have flow |

**Acceptance**:
- [ ] Open browser to `localhost:5173`
- [ ] Grant camera + mic permissions
- [ ] Say "Chef, I have chicken thighs, garlic, and butter"
- [ ] Hear agent respond with spoken audio within ~2s
- [ ] See transcript update with both cook and chef speech
- [ ] Agent transitions quickly from ingredient intake to live cook mode
- [ ] Agent calls `set_timer` proactively and timer card appears in UI without being asked
- [ ] Demo speed toggle compresses timer durations and timer alerts still fire correctly
- [ ] Interrupt agent mid-sentence and confirm playback stops cleanly
- [ ] At least two demo-safe proactive coaching moments work locally, such as:
  - knife/hand safety correction
  - "don't move it yet" or early-flip warning
  - garlic browning / rotate-pan correction
- [ ] Session badge shows session ID, RTT, and active timer/event count
- [ ] No console errors, no WebSocket disconnects over 5+ minutes

---

## Phase 7: Deployment

### T-18: Deploy script and Cloud Run deployment

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-17 |
| **Produces** | `scripts/deploy.sh` |
| **Design ref** | 4.1, 4.3 |

**Acceptance**:
- [ ] `scripts/deploy.sh` builds frontend, enables GCP services, and deploys to Cloud Run
- [ ] Cloud Run service `souschef-live` running in `us-central1`
- [ ] Session affinity, 3600s timeout, min-instances=1, concurrency=1, 2 CPU / 1Gi memory
- [ ] `GEMINI_API_KEY`, `MODEL`, `SESSION_TIME_LIMIT`, and `DEV_MODE` set as env vars
- [ ] WebSocket connections work through Cloud Run HTTPS endpoint
- [ ] Idempotent (safe to run repeatedly)

### T-19: Production smoke test

| Field | Value |
|-------|-------|
| **Status** | `done (harness-validated)` |
| **Depends on** | T-18 |
| **Produces** | verified working deployed system |
| **Design ref** | 6.4, 6.5 |

**Acceptance**:
- [ ] Open deployed URL on phone
- [ ] Full E2E smoke test checklist passes (same as T-17 but on deployed infra)
- [ ] Session badge shows `us-central1 | Cloud Run`, RTT, and active timer/event count
- [ ] Voice response latency < 2s
- [ ] No cold start delays (min instance warm)
- [ ] Reconnect with same `session_id` restores session state when the in-memory session still exists

---

## Phase 8: Polish & Submission

### T-20: README

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-18 |
| **Produces** | `README.md` |
| **Design ref** | requirements US-6.3 |

**Acceptance**:
- [ ] Project overview and architecture diagram
- [ ] Prerequisites (Python 3.10+, Node 18+, gcloud CLI, Gemini API key)
- [ ] Local development quickstart (3-5 steps)
- [ ] Environment variable reference
- [ ] Deployment instructions
- [ ] Tech stack summary (google-genai SDK, FastAPI, Vite, Cloud Run)
- [ ] Link to live demo URL
- [ ] Hackathon context and challenge link
- [ ] Spin-up instructions are clear enough for judges to reproduce the app

### T-21: Submission assets and compliance artifacts

| Field | Value |
|-------|-------|
| **Status** | `done` |
| **Depends on** | T-18, T-20 |
| **Produces** | submission-ready assets in `docs/` and repo root |
| **Design ref** | hackathon.md submission requirements |

**Acceptance**:
- [ ] Repo includes a clear architecture diagram artifact judges can open quickly
- [ ] Repo includes a concise project description covering features, technologies, data sources, and learnings
- [ ] Separate proof-of-Google-Cloud-deployment plan is prepared, including the exact Cloud Run console/logs/screens to show
- [ ] Deploy automation is easy for judges to find in the repo (`scripts/deploy.sh` or equivalent)
- [ ] Public repo checklist is complete: README, architecture, deploy script, and demo link placeholders

### T-22: Demo rehearsal and recording prep

| Field | Value |
|-------|-------|
| **Status** | `pending` |
| **Depends on** | T-19, T-21 |
| **Produces** | verified demo-ready system and recording plan |
| **Design ref** | 6.4, 6.5, demo.md, hackathon.md |

**Acceptance**:
- [ ] Full cook-through rehearsal with demo speed enabled
- [ ] Demo hits the must-have beats from `docs/demo.md`:
  - quick recipe suggestion from ingredients
  - live cook mode transition
  - proactive visual correction
  - proactive sear timer
  - barge-in interruption
  - proactive flip/rest alert
- [ ] Verify all demo failure mitigations from design 6.5:
  - headphones to prevent feedback loop
  - good lighting and camera angle
  - stable network
  - system instruction tuned for proactivity
- [ ] Main demo fits within the 4-minute limit
- [ ] Separate cloud deployment proof recording is rehearsed
- [ ] Fallback plan documented if agent is not proactive enough

---

## Dependency Graph

```
T-01 (scaffold)
 ├── T-02 (session store)
 │    └── T-04 (tools)
 ├── T-03 (gemini bridge)
 ├── T-05 (system instruction)
 ├── T-07 (capture worklet)
 ├── T-08 (playback worklet)
 ├── T-10 (ws client)
 ├── T-11 (html/css)
 └── T-12 (state mgmt)

T-07 + T-08 → T-09 (media utils)

T-02 + T-03 + T-04 + T-05 → T-06 (fastapi server)

T-09 + T-10 + T-11 + T-12 → T-13 (ui + main.js)

T-02 + T-04 + T-10 + T-12 → T-14 (unit tests)

T-06 + T-10 → T-15 (integration tests)

T-06 + T-13 → T-16 (dev script)

T-14 + T-15 + T-16 → T-17 (local smoke test)

T-17 → T-18 (deploy) → T-19 (prod smoke test)

T-18 → T-20 (readme)

T-18 + T-20 → T-21 (submission assets)

T-19 + T-21 → T-22 (demo prep)
```

---

## Execution Notes

- **Parallelism**: After T-01, backend tasks (T-02 through T-06) and frontend tasks (T-07 through T-13) can proceed in parallel.
- **Delivery path**: The true delivery path is two converging branches rather than one straight line:
  - backend branch: T-01 -> T-02/T-03/T-04/T-05 -> T-06
  - frontend branch: T-01 -> T-07/T-08 -> T-09 + T-10 + T-11 + T-12 -> T-13
  - convergence: T-16 -> T-17 -> T-18 -> T-19 -> T-22
- **Reliability gates**: T-14 and T-15 should pass before T-18. T-17 and T-19 are the real go/no-go checks for demo and deploy confidence.
- **Timebox**: Each task targets 30-90 minutes. If a task exceeds 2 hours, split it or cut scope.
- **Testing**: T-14 and T-15 provide automated guardrails, but T-17 is the first full product-quality gate and T-19 is the production gate.
