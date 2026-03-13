# SousChef Live -- Autonomous Development Harness

> Read this file and [tasks.md](tasks.md) together during every implementation step.
> `tasks.md` defines what to build. `harness.md` defines how to prove it works quickly, cheaply, and repeatedly.
> A task is not `done` until the required harness tier passes and produces evidence.

---

## 1. Purpose

The harness exists to make development genuinely autonomous.

Without a strong harness, the implementing agent will:
- overuse slow manual smoke tests,
- burn paid Gemini calls on bugs that should be caught offline,
- fail to localize regressions quickly,
- and struggle to iterate on a live multimodal system with confidence.

This document therefore treats the harness as a first-class product for the developer/agent.

Primary goals:
- give fast feedback for every component,
- separate deterministic plumbing bugs from model-behavior issues,
- make regressions obvious,
- provide structured artifacts for debugging,
- and support repeated iteration until the app is demo-ready.

---

## 2. Non-Negotiable Rules

1. Implementers must keep `docs/tasks.md` and `docs/harness.md` open together.
2. Prefer the cheapest deterministic feedback loop first. Use the real Gemini Live API last, not first.
3. Every harness tier must emit artifacts, not just a pass/fail exit code.
4. A broken or missing harness is a blocker, not a nice-to-have.
5. Instrumentation and observability are part of correctness. If a failure cannot be diagnosed quickly, the task is incomplete.
6. No real user live media is persisted by the harness. Only synthetic or explicitly prepared test fixtures may be stored.
7. If a code change affects a contract, protocol, or UX-critical behavior, the next-higher harness tier must be re-run before marking the task done.

---

## 3. Feedback Loop Targets

| Tier | Purpose | Target Runtime | Uses Real Gemini? | Blocks Task Completion? |
|------|---------|----------------|-------------------|-------------------------|
| `static` | import/build/lint/smoke sanity | `< 15s` | No | Yes |
| `unit` | pure logic correctness | `< 30s` | No | Yes |
| `integration` | backend contracts and protocol wiring | `< 2m` | No by default | Yes |
| `system` | browser + backend + mocked media behavior | `< 5m` | No by default | Yes |
| `live` | real Gemini Live regression pack | `< 10m` | Yes | Required for model-facing or demo-critical behavior |
| `deploy` | deployed Cloud Run proof + smoke | `< 15m` | Yes | Required before demo/submission |

Success criteria:
- most edits should get useful feedback within 30 seconds to 2 minutes,
- full local confidence should be reachable in under 5 minutes,
- and real-model confirmation should be reserved for final validation of multimodal and prompt behavior.

---

## 4. Harness Architecture

The harness must validate the app at multiple layers:

1. `Static checks`
   - imports, build steps, smoke startup, dependency sanity

2. `Deterministic unit harness`
   - session store
   - timer scheduler
   - step state machine
   - prompt/tool declaration shape
   - client parser/state reducers

3. `Deterministic integration harness`
   - FastAPI WebSocket protocol
   - mixed binary + JSON message routing
   - tool dispatch and UI events
   - reconnect primer logic
   - cleanup and failure handling

4. `Deterministic system harness`
   - real browser automation
   - mocked or fixture-driven media
   - DOM updates
   - transcript, timers, barge-in UI behavior
   - degraded modes and permission failures

5. `Selective live harness`
   - minimal real Gemini Live sessions
   - judge-critical scenarios only
   - latency and proactivity verification
   - prompt/regression checks with tolerant assertions

6. `Deployment/demo harness`
   - Cloud Run smoke
   - session badge proof
   - reconnect check on deployed infra
   - architecture/submission artifact readiness

The architecture should always support two modes:
- `real mode`: talks to the actual Gemini Live API
- `fake mode`: uses deterministic scripted responses and events

The fake mode is the foundation of autonomous iteration.

---

## 5. Mandatory Harness Switches

The app should expose explicit runtime switches so the harness can run deterministically.

### Backend

Recommended env vars:
- `LIVE_BACKEND_MODE=real|fake`
- `HARNESS_SCENARIO=<scenario_id>`
- `HARNESS_ARTIFACT_DIR=<path>`
- `LOG_FORMAT=json`
- `LOG_LEVEL=INFO|DEBUG`

Behavior:
- `real`: backend uses `genai.Client(api_key=...)`
- `fake`: backend swaps the real live client/session for a deterministic scripted fake

### Frontend

Recommended options:
- query param `?harness=1`
- query param `?scenario=<scenario_id>`
- query param `?media=fixture|real`

Behavior:
- `real` media mode uses actual camera + mic
- `fixture` media mode swaps `AudioStreamer` and `VideoStreamer` for fixture-driven implementations

This avoids fragile OS-level fake device setup for every browser run and gives the agent much tighter control.

---

## 6. Harness Workstreams

These workstreams are separate from product tasks and should be treated as prerequisite infrastructure for fast autonomous iteration.

### H-01: Structured Instrumentation Foundation

**Outputs**:
- `server/observability.py`
- `frontend/src/debug.js` or equivalent
- common run ID / session ID utilities

**Acceptance**:
- Every backend request/session gets a `run_id` and `session_id`
- Structured JSON logs are emitted for key lifecycle events
- Frontend exposes a bounded in-memory debug event buffer in dev/harness mode
- Cloud Run can ingest backend JSON logs directly from stdout
- Local runs write artifacts to `artifacts/harness/<run_id>/`

### H-02: Fake Gemini Live Adapter

**Outputs**:
- `harness/fakes/fake_genai.py`
- `harness/fakes/fake_live_session.py`

**Acceptance**:
- Implements the subset of the real client/session contract the app actually uses
- Can emit scripted:
  - audio bytes
  - input/output transcription events
  - `interrupted`
  - `turnComplete`
  - tool calls
  - tool response acknowledgements
- Records inbound audio/image/text payloads for assertions
- Can inject delays, failures, and disconnects deterministically

### H-03: Scenario DSL and Fixture Packs

**Outputs**:
- `harness/scenarios/*.yaml` or `*.json`
- `harness/fixtures/audio/`
- `harness/fixtures/images/`
- `harness/fixtures/transcripts/`

**Acceptance**:
- Scenarios are declarative and replayable
- Each scenario defines:
  - setup config
  - ordered inbound media/messages
  - fake model events
  - expected state transitions
  - latency budgets
  - required artifacts
- Fixture media is synthetic or explicitly prepared test media only

### H-04: Unit Harness

**Outputs**:
- `server/tests/unit/`
- `frontend/tests/unit/`
- `scripts/harness/unit.sh`

**Acceptance**:
- No network calls
- No browser required
- Covers session store, timers, step transitions, parser behavior, prompt/tool declaration structure
- Produces machine-readable report and coverage summary

### H-05: Backend Integration Harness

**Outputs**:
- `server/tests/integration/`
- `scripts/harness/integration.sh`

**Acceptance**:
- Runs FastAPI app against the fake live backend
- Uses a real WebSocket client
- Verifies protocol routing, reconnect, cleanup, tool events, and failure handling
- Produces event traces and summarized pass/fail output

### H-06: Browser/System Harness

**Outputs**:
- `frontend/tests/system/`
- `scripts/harness/system.sh`

**Acceptance**:
- Uses browser automation such as Playwright
- Runs frontend in harness mode with fixture media
- Verifies DOM/state changes for judge-visible behavior
- Captures screenshots, console logs, and optional trace/video
- Does not require manual permission clicking in automated runs

### H-07: Live Regression Harness

**Outputs**:
- `tests/live/`
- `scripts/harness/live.sh`

**Acceptance**:
- Uses the real `gemini-2.5-flash-native-audio-latest` model
- Runs only critical scenarios that truly require the real model
- Uses tolerant assertions:
  - latency within budget
  - a tool call happened
  - proactive guidance happened
  - interruption happened cleanly
  - reconnect recovered when expected
- Never depends on exact wording from the model

### H-08: Deployment and Demo Harness

**Outputs**:
- `scripts/harness/deploy-smoke.sh`
- `scripts/harness/demo-checklist.md`
- proof artifact checklist in `artifacts/harness/`

**Acceptance**:
- Validates deployed Cloud Run endpoint
- Confirms session badge and deployment proof elements appear
- Produces a checklist for the separate Google Cloud proof recording
- Rehearses the exact judge-facing scenarios from `docs/demo.md`

---

## 7. Recommended Directory Layout

```text
harness/
  fakes/
    fake_genai.py
    fake_live_session.py
  fixtures/
    audio/
    images/
    transcripts/
  scenarios/
    recipe_start.yaml
    pan_not_ready.yaml
    proactive_timer.yaml
    barge_in.yaml
    reconnect_restore.yaml
    tool_failure.yaml
    permission_denied.yaml
  reports/
    schema.json

scripts/
  harness/
    check.sh
    unit.sh
    integration.sh
    system.sh
    live.sh
    deploy-smoke.sh
    run-all.sh

artifacts/
  harness/
    <run_id>/
      report.json
      summary.md
      backend.log
      frontend-events.json
      screenshots/
      traces/
```

Test code can still live under `server/tests/` and `frontend/tests/`, but the harness-specific fakes, scenarios, scripts, and artifacts should be easy to find from one place.

---

## 8. Required Scenario Catalog

The harness must cover at least these scenarios.

| Scenario | Tier | Why It Matters |
|----------|------|----------------|
| `recipe_start` | unit/system/live | verifies ingredient intake -> cook mode transition |
| `knife_safety` | system/live | verifies proactive visual/safety correction |
| `pan_not_ready` | system/live | verifies honest multimodal reasoning without false certainty |
| `proactive_timer` | integration/system/live | verifies `set_timer` fires without user request |
| `barge_in_interrupt` | integration/system/live | verifies interruption handling and playback stop |
| `flip_alert` | integration/system/live | verifies pre-alert/final alert timing path |
| `reconnect_restore` | integration/deploy | verifies reconnect primer and state restoration |
| `tool_failure` | integration | verifies graceful degradation and user-visible warning path |
| `permission_denied` | system | verifies audio-only or retry fallback |
| `audio_playback_failure` | system | verifies transcript fallback path |
| `session_timeout` | integration/deploy | verifies timeout/cleanup behavior |

Judge-critical scenarios are:
- `recipe_start`
- `knife_safety`
- `pan_not_ready`
- `proactive_timer`
- `barge_in_interrupt`
- `flip_alert`
- `reconnect_restore`

---

## 9. Instrumentation and Observability Contract

### 9.1 Required Event Types

The backend must log events like:
- `ws_connect`
- `ws_disconnect`
- `setup_received`
- `live_connect_start`
- `live_connect_ok`
- `live_connect_error`
- `audio_in_chunk`
- `image_in_frame`
- `text_in_message`
- `tool_call_received`
- `tool_call_completed`
- `tool_call_failed`
- `timer_scheduled`
- `timer_prealert_fired`
- `timer_expired`
- `state_update_sent`
- `audio_out_chunk`
- `interrupt_received`
- `turn_complete`
- `reconnect_primer_sent`
- `session_cleanup`

The frontend must surface events like:
- `permissions_granted`
- `permissions_denied`
- `ws_open`
- `ws_close`
- `ws_reconnect_attempt`
- `audio_capture_started`
- `audio_playback_started`
- `audio_playback_interrupted`
- `timer_card_rendered`
- `transcript_updated`
- `error_banner_shown`

### 9.2 Required Log Fields

Every structured event should include:
- `timestamp`
- `run_id`
- `session_id`
- `component`
- `event_type`
- `severity`
- `scenario_id` when in harness mode
- `latency_ms` when relevant
- `details` object with event-specific metadata

Example:

```json
{
  "timestamp": "2026-03-13T18:21:14.120Z",
  "run_id": "run_20260313_182114_001",
  "session_id": "abc123",
  "component": "backend.timer",
  "event_type": "timer_prealert_fired",
  "severity": "INFO",
  "latency_ms": 0,
  "details": {
    "timer_id": "tmr_01",
    "label": "sear_side_1",
    "remaining_seconds": 15
  }
}
```

### 9.3 Required Metrics

The harness should compute and report:
- `ws_connect_ms`
- `live_connect_ms`
- `first_audio_response_ms`
- `turn_complete_ms`
- `tool_execution_ms`
- `timer_schedule_lag_ms`
- `timer_fire_lag_ms`
- `reconnect_recovery_ms`
- `audio_out_buffer_ms`
- `frontend_rtt_ms`
- `error_count_by_type`
- `disconnect_count`
- `dropped_frame_count`
- `max_queue_depth_by_queue`

### 9.4 Artifact Outputs

Every non-trivial run should emit:
- `report.json`
- `summary.md`
- backend structured log
- frontend event log
- screenshots for browser/system/deploy runs
- traces or videos for browser failures when practical

### 9.5 Privacy Rule

The harness must not persist arbitrary live user media.
Allowed persisted media:
- synthetic fixtures
- prepared test recordings explicitly added for harness use
- screenshots/videos from automated browser runs in local or CI environments

---

## 10. Suggested Command Surface

These commands are recommendations; exact naming can vary, but the capabilities must exist.

| Command | Purpose |
|---------|---------|
| `./scripts/harness/check.sh` | import/build/lint/smoke sanity |
| `./scripts/harness/unit.sh` | all unit tests |
| `./scripts/harness/integration.sh` | backend integration suite with fake live backend |
| `./scripts/harness/system.sh` | browser automation with fixture media |
| `./scripts/harness/live.sh` | real Gemini Live regression pack |
| `./scripts/harness/deploy-smoke.sh` | deployed Cloud Run smoke and proof checks |
| `./scripts/harness/run-all.sh` | ordered execution of check -> unit -> integration -> system, plus optional `--live` and `--deploy` |

Each command should:
- fail non-zero on harness failure,
- print a concise terminal summary,
- and write detailed artifacts to `artifacts/harness/<run_id>/`.

---

## 11. Pass/Fail Rules

### Before a component task can be marked `done`

- required `static` checks pass
- required harness tier for that task passes
- artifacts exist and identify what was validated
- failures, if any, are understood and explicitly accepted as out of scope

### Before a model-facing or UX-critical task can be marked `done`

- deterministic harness passes
- relevant live regression scenario passes at least once after the change

### Before deployment

- unit + integration + system harness green
- judge-critical scenario pack green locally
- observability fields present in logs/reports

### Before demo/submission

- deployed smoke green
- judge-critical live scenarios green on deployed infra
- architecture/proof artifacts ready

---

## 12. Task-to-Harness Gate Mapping

Use this table together with `docs/tasks.md`.

| Task Group | Required Harness Gates Before `done` |
|------------|--------------------------------------|
| `T-01` scaffold | `static` |
| `T-02`, `T-04`, `T-05`, `T-12` pure logic/state/prompt | `unit` |
| `T-03`, `T-06`, `T-10` bridge/server/protocol | `unit` + `integration`, then `live` smoke if model-facing behavior changed |
| `T-07`, `T-08`, `T-09`, `T-11`, `T-13` media and UI | `unit` where applicable + `system` |
| `T-14`, `T-15`, `T-16` harness/test/dev plumbing | the harness tier being built must test itself with a smoke case |
| `T-17` local E2E | `system` + judge-critical `live` pack |
| `T-18` deploy | `unit` + `integration` + `system` + deploy smoke |
| `T-19` production smoke | deploy smoke + selected `live` scenarios on deployed app |
| `T-20`, `T-21`, `T-22` docs/submission/demo | deployed artifacts + demo checklist + proof checklist |

If `tasks.md` and `harness.md` ever seem in tension, do not lower the harness bar just to satisfy the task checklist.

---

## 13. Autonomous Agent Operating Protocol

This is the required implementation loop.

1. Open `docs/tasks.md` and `docs/harness.md` together.
2. Choose the next task and mark it `in_progress`.
3. Identify the lowest harness tier that should fail if the implementation is wrong.
4. If that harness tier does not exist yet, build the harness capability first.
5. Make the smallest possible code change.
6. Run the lowest-cost relevant harness command.
7. Inspect both terminal output and generated artifacts.
8. Iterate until the relevant tier is green.
9. If the change affects a public contract, UX behavior, reconnect logic, or model-facing behavior, run the next-higher tier too.
10. Only then mark the task `done`.

Important:
- Do not jump directly to live manual testing for a bug that should be reproducible offline.
- Do not trust a green deploy if there is no structured artifact trail for the run.
- Do not trust a passing live test if deterministic harness layers are missing.

---

## 14. Minimum Viable Harness Build Order

Build the harness in this order:

1. `H-01` structured instrumentation
2. `H-02` fake Gemini Live adapter
3. `H-03` scenario DSL and fixture packs
4. `H-04` unit harness
5. `H-05` backend integration harness
6. `H-06` browser/system harness
7. `H-07` live regression harness
8. `H-08` deployment/demo harness

Reason:
- instrumentation makes failures diagnosable,
- the fake live adapter makes iteration cheap,
- scenario fixtures give the unit and integration harnesses something concrete to run against,
- unit + integration harnesses make backend work safe,
- system harness makes browser/media work repeatable,
- and live/deploy harnesses confirm the real demo path only after the lower tiers are solid.

---

## 15. Definition of Ready for Autonomous Development

The project is ready for autonomous feature implementation when all of the following are true:
- deterministic fake live backend exists,
- scenario fixtures exist for judge-critical flows,
- structured logging and artifact reports exist,
- unit and integration suites run in one command,
- browser/system harness can run without manual media setup,
- and at least one real Gemini Live regression scenario can be executed on demand.

Until then, harness work is the highest-leverage work in the repo.
