# SousChef Live — Shipped Project Summary

SousChef Live is a real-time AI sous-chef built for the Gemini Live Agent Challenge. It streams live microphone audio and kitchen video from the browser to a FastAPI backend on Cloud Run, which bridges to the Gemini Live API using the raw `google-genai` SDK.

The product is intentionally designed as a live cooking companion rather than a recipe chatbot. The goal is not "tell me a recipe." The goal is "cook with me."

---

## What Is Built

### Core product behavior

- The cook can talk naturally to the chef and hear native-audio responses.
- The browser continuously streams microphone audio and camera frames during a session.
- The chef can be interrupted mid-response and recover cleanly.
- The chef can suggest a recipe from available ingredients and retain that recipe in session state.
- The chef can proactively set timers, track the current cooking step, and restore state on reconnect when the in-memory session still exists.
- The UI shows the live camera feed, recipe chip, step chip, monitoring status, timer cards, transcript panel, and deployment/session badge.

### Backend architecture

- FastAPI WebSocket server on Cloud Run
- Raw Gemini Live API connection through `google-genai`
- In-memory `SessionContext` with timers and reconnect primer support
- Server-authoritative system instruction and tool declarations
- Four implemented tools:
  - `update_recipe`
  - `set_timer`
  - `update_cooking_step`
  - `get_cooking_state`

### Frontend architecture

- Vanilla JavaScript + Vite
- `AudioWorklet` capture at 16kHz PCM
- `AudioWorklet` playback at 24kHz PCM
- JPEG frame capture at 1 FPS
- WebSocket client with reconnect support
- Product UI optimized for demo readability

### Deployment

- Deployed to Google Cloud Run in two regions:
  - Judges / repository default (`us-central1`): `https://souschef-live-5z4a6smnda-uc.a.run.app`
  - Europe demo (`europe-west1`): `https://souschef-live-5z4a6smnda-ew.a.run.app`
- `scripts/deploy.sh` defaults to `us-central1`; demoers can override with `REGION=europe-west1`
- Session affinity enabled
- `min-instances=1`
- `concurrency=1`
- `timeout=3600`
- Frontend built and served from the same service

---

## Why This Is Distinct

SousChef Live is differentiated from hands-free recipe readers by three product behaviors:

1. **Continuous multimodal supervision**
   - The agent receives ongoing audio and video, not just one-shot prompts.

2. **Proactive intervention**
   - The system instruction pushes the chef to speak up when timing, safety, or visible mistakes matter.

3. **Stateful cooking flow**
   - The app persists recipe context, cooking step, timer state, and reconnect primers instead of treating each interaction like a fresh chat turn.

---

## What Has Been Validated

### Automated validation

The codebase has passing automated validation across the main testing layers:

- 92 backend tests total (77 unit + 15 integration: memory, session store, tools, prompts, observability, WebSocket lifecycle)
- 40 live API and deployed E2E tests (Gemini Live smoke, deployed WebSocket, session memory reconnect, semantic verification, compression/resumption config, multi-turn stability, vision scenarios, persona guardrails, timer lifecycle, demo flow simulation)
- 32 Playwright browser tests (landing page, cooking screen, UI elements, glassmorphism, session lifecycle, transcript, demo speed, visual verification)

This validates:

- WebSocket connectivity and protocol correctness
- Frontend rendering and UI transitions
- Health endpoint behavior
- Real Gemini Live session setup, audio response, and transcription
- Tool call execution (update_recipe, set_timer, update_cooking_step, get_cooking_state)
- Graceful session shutdown and transient disconnect handling
- Session memory: state hydration on reconnect, transcript accumulation, reconnect primer continuity
- Context window compression and session resumption configuration
- Agent persona compliance and semantic correctness of responses
- Full production observability (40+ structured event types in Cloud Run logs)

### Deployment validation

- Cloud Run deployment is live and serving traffic
- health endpoint responds successfully
- deployed frontend is reachable
- deployed WebSocket path works
- deployed backend can call the real Gemini Live API

---

## What Is Still Manual

The remaining work is demo rehearsal, not core implementation:

- full real-device cook-through
- mobile Safari / phone-camera rehearsal
- real kitchen lighting and camera-angle rehearsal
- validating proactive corrections against genuine cooking input
- recording the final 4-minute demo and separate Cloud deployment proof

These are tracked explicitly in `docs/tasks.md` as the remaining `T-22` demo-prep gate.

---

## Shipped Constraints

These are intentional scope decisions, not missing implementation bugs:

- in-memory session state instead of Firestore
- single-user demo orientation rather than multi-user infrastructure
- no generated image overlays or coaching arrows
- no difficulty modes
- no persisted media storage
- no smart-kitchen integrations

---

## Submission Assets Present

The repository includes:

- technical design in `docs/design.md`
- user stories in `docs/requirements.md`
- executable task plan in `docs/tasks.md`
- harness strategy in `docs/harness.md`
- final demo plan in `docs/demo.md`
- deployment proof plan in `docs/deployment-proof-plan.md`
- fallback plan in `docs/fallback-plan.md`
- Cloud Run deploy script in `scripts/deploy.sh`
- README with setup and deployment instructions

---

## Bottom Line

SousChef Live is now a substantially built, tested, and deployed Live Agent entry:

- built on Gemini Live API
- hosted on Google Cloud
- multimodal
- voice-first
- interruptible
- proactive
- stateful
- testable with both harness and deployed E2E coverage

The primary remaining risk is demo performance under real kitchen conditions, which is now a rehearsal problem rather than a missing-product problem.
