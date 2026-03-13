# SousChef Live -- Requirements

## Overview

SousChef Live is a real-time AI sous-chef that sees, hears, and proactively guides users while they cook. It uses continuous video and audio streaming to provide hands-free cooking supervision -- not just recipe reading, but live technique correction, timing management, and safety guidance.

**Category**: Gemini Live Agent Challenge -- Live Agents  
**Mandatory Tech**: Gemini Live API / GenAI SDK, Google Cloud  
**Deadline**: March 16, 2026

---

## Actors

- **Cook**: The user cooking in their kitchen with a camera and microphone
- **Chef** (Agent): The AI sous-chef persona that observes and guides
- **System**: The backend infrastructure (timers, state, deployment)

---

## Epic 1: Live Voice Interaction

The cook can have a natural, hands-free voice conversation with the chef while cooking.

### US-1.1: Natural Voice Communication

> **As a** cook,  
> **I want to** speak naturally to the chef and hear spoken responses,  
> **So that** I never need to touch my phone or type while cooking.

**Acceptance Criteria**:
- Cook's microphone audio streams continuously to the agent
- Agent responds with natural spoken audio (not text-to-speech)
- Latency between cook finishing a sentence and agent starting response is under 2 seconds
- Agent uses Voice Activity Detection to know when cook is done speaking

### US-1.2: Barge-In / Interruption

> **As a** cook,  
> **I want to** interrupt the chef mid-sentence with a question,  
> **So that** I get immediate answers without waiting for it to finish talking.

**Acceptance Criteria**:
- Cook can speak while agent is speaking
- Agent stops its current response immediately upon detecting cook's voice
- Agent addresses the interruption, then optionally resumes prior guidance
- No audio overlap or garbled output

### US-1.3: Chef Persona

> **As a** cook,  
> **I want** the chef to have a calm, confident personality,  
> **So that** the experience feels like cooking with a real mentor, not a robot.

**Acceptance Criteria**:
- Agent maintains a consistent persona: calm, encouraging, professional chef
- Responses are concise (1-2 sentences max per turn)
- Agent uses cooking terminology naturally
- Agent never says "as an AI" or breaks character

---

## Epic 2: Live Visual Supervision

The chef continuously watches the cooking through the camera and proactively provides guidance based on what it sees.

### US-2.1: Continuous Camera Streaming

> **As a** cook,  
> **I want** the chef to see my cooking through my phone/laptop camera,  
> **So that** it can observe what I'm doing without me describing it.

**Acceptance Criteria**:
- Video frames captured from user's camera at ~1 FPS
- Frames sent to agent as realtime image blobs via WebSocket
- Agent can reference what it sees ("I see the pan", "your garlic is browning")
- Works with standard phone or laptop cameras

### US-2.2: Proactive Visual Corrections

> **As a** cook,  
> **I want** the chef to speak up when it sees something wrong,  
> **So that** I catch mistakes before they ruin the dish.

**Acceptance Criteria**:
- Agent initiates speech without being asked when it detects:
  - Unsafe knife grip or technique
  - Pan not hot enough (no shimmer, weak sizzle)
  - Food browning too fast or burning
  - Incorrect timing (flipping too early/late)
- Corrections are phrased as observations, not false certainty ("I'm not seeing shimmer yet" not "the pan is 300 degrees")

### US-2.3: Audio Cue Awareness

> **As a** cook,  
> **I want** the chef to listen to cooking sounds (sizzle, crackling),  
> **So that** it can use audio signals alongside visual ones for better guidance.

**Acceptance Criteria**:
- Agent can interpret sizzle intensity as a heat indicator
- Agent references audio cues in guidance ("the sizzle is weak", "that crackling means the butter is ready")
- Works alongside voice -- agent distinguishes speech from cooking sounds

---

## Epic 3: Cooking State Management

The chef tracks where the cook is in the recipe and manages the progression through steps.

### US-3.1: Recipe Generation from Ingredients

> **As a** cook,  
> **I want to** tell the chef what ingredients I have and get a dish suggestion,  
> **So that** I can start cooking without browsing recipes.

**Acceptance Criteria**:
- Cook describes available ingredients via voice (optionally shows them on camera)
- Agent suggests a dish and briefly outlines the steps
- Agent transitions into "cook mode" when the cook is ready
- Recipe context persists throughout the session

### US-3.2: Step State Machine

> **As a** cook,  
> **I want** the chef to know which step I'm on,  
> **So that** guidance is relevant to what I'm currently doing, not generic.

**Acceptance Criteria**:
- Agent tracks cooking steps: prep -> heat -> sear_side_1 -> flip -> sear_side_2 -> baste -> rest -> done
- Agent advances steps based on visual/audio observation or cook confirmation
- Agent uses `update_cooking_step` tool to persist state
- Current step is visible in the UI

### US-3.3: Ingredient Substitution

> **As a** cook,  
> **I want to** tell the chef I'm missing an ingredient and get a substitution,  
> **So that** I can keep cooking without stopping to go to the store.

**Acceptance Criteria**:
- Cook says "I don't have X"
- Agent suggests substitute grounded in the current recipe context
- Agent adjusts quantities if needed ("use rosemary, but half the amount")

---

## Epic 4: Timer Management

The chef proactively manages timing-sensitive steps without the cook needing to ask.

### US-4.1: Proactive Timer Suggestions

> **As a** cook,  
> **I want** the chef to suggest timers automatically when a timing-sensitive step begins,  
> **So that** I don't have to remember to set one myself.

**Acceptance Criteria**:
- Agent calls `set_timer` tool when cook begins a timed step (searing, resting, etc.)
- Agent announces the timer: "Starting a 2-minute sear timer. I'll alert you."
- Timer appears in the UI automatically
- Agent does NOT wait for cook to ask for a timer

### US-4.2: Timer Alerts

> **As a** cook,  
> **I want** the chef to alert me when a timer is about to expire or has expired,  
> **So that** I take action at the right moment.

**Acceptance Criteria**:
- Agent gives a pre-alert ~15 seconds before expiry ("almost time to flip")
- Agent gives a final alert at expiry ("flip now")
- Alert is spoken aloud, not just visual
- If cook is mid-conversation, alert still fires (priority interrupt)

### US-4.3: Demo Speed Mode

> **As a** presenter,  
> **I want** a "demo speed" toggle that compresses timer durations,  
> **So that** I can show the full cooking flow in a 4-minute demo video.

**Acceptance Criteria**:
- UI toggle: "Demo Speed (10x)"
- All timer durations divided by 10 when active
- Agent behavior otherwise identical
- Toggle is visible in UI (shows judges it's intentional, not faked)

---

## Epic 5: Frontend Experience

The cook sees a clean, product-grade interface that proves this is a real deployed system.

### US-5.1: Live Camera Feed

> **As a** cook,  
> **I want to** see my own camera feed on screen,  
> **So that** I know what the chef is seeing.

**Acceptance Criteria**:
- Camera feed displayed prominently (primary visual element)
- No noticeable lag between real world and displayed feed
- Works on mobile (Safari, Chrome) and desktop

### US-5.2: Status Chips / Overlays

> **As a** cook (and judge),  
> **I want to** see the current cooking state and monitoring status,  
> **So that** I understand what the agent is tracking.

**Acceptance Criteria**:
- Overlay chips on or near the video feed:
  - Current step: "Step: Searing Side 1"
  - Monitoring status: "Monitoring heat..."
  - Active timers: "Timer: 1:45 remaining"
- Chips update in real-time as agent calls tools

### US-5.3: Session Badge

> **As a** judge reviewing the demo,  
> **I want to** see deployment proof embedded in the product UI,  
> **So that** I know this is running on real cloud infrastructure.

**Acceptance Criteria**:
- Small badge visible in UI: "Live Session: us-central1 | Cloud Run"
- Latency indicator: "RTT: ~420ms"
- Session ID visible (proves real session, not recording)
- Active timer/event count visible when relevant (for example "Timers: 1 active")

### US-5.4: Transcript Panel

> **As a** cook,  
> **I want to** see a scrolling transcript of the conversation,  
> **So that** I can re-read instructions if I missed something the chef said.

**Acceptance Criteria**:
- Collapsible panel showing conversation history
- Distinguishes cook's speech from agent's speech
- Auto-scrolls to latest message
- Uses audio transcription from Gemini Live (input + output transcription)

---

## Epic 6: Deployment & Infrastructure

The system runs on Google Cloud and can be reproduced from the repository.

### US-6.1: Cloud Run Deployment

> **As a** developer,  
> **I want** the backend deployed on Cloud Run,  
> **So that** it satisfies the hackathon's Google Cloud hosting requirement.

**Acceptance Criteria**:
- Dockerfile builds and runs the FastAPI server
- Deployed to Cloud Run in `us-central1`
- WebSocket connections work through Cloud Run
- Runtime environment variables include `GEMINI_API_KEY`, `MODEL`, `SESSION_TIME_LIMIT`, and `DEV_MODE`

### US-6.2: Automated Deployment Script

> **As a** developer (and for bonus points),  
> **I want** a single `deploy.sh` that deploys everything,  
> **So that** judges can see infrastructure-as-code and I get bonus points.

**Acceptance Criteria**:
- `deploy.sh` creates/updates Cloud Run service
- Handles environment variable configuration
- Idempotent (safe to run multiple times)
- Documented in README

### US-6.3: Reproducible Setup

> **As a** judge,  
> **I want** clear README instructions to spin up the project,  
> **So that** I can verify the project is reproducible.

**Acceptance Criteria**:
- README covers: prerequisites, local dev setup, environment variables, deployment
- `requirements.txt` with pinned versions
- `.env.example` with all required variables
- Works locally with `.env` + `GEMINI_API_KEY`

### US-6.4: Submission-Ready Hackathon Assets

> **As a** judge,  
> **I want** the repo and submission assets to clearly prove the project is real, deployed, and reproducible,  
> **So that** I can verify both technical quality and challenge compliance quickly.

**Acceptance Criteria**:
- Repo includes a clear architecture diagram
- Repo includes a concise project description covering features, technologies, and learnings
- A separate proof-of-Google-Cloud-deployment artifact or recording plan is prepared
- The 4-minute demo plan emphasizes real-time multimodal behavior, proactivity, and interruption handling

---

## Non-Functional Requirements

### NFR-1: Latency
- Agent voice response latency < 2 seconds from end of cook's speech
- Video frame processing does not block audio responsiveness

### NFR-2: Session Duration
- Session supports at least 10 minutes of continuous cooking
- Session state restore configured for reconnection tolerance

### NFR-3: Browser Compatibility
- Works on Chrome (desktop + Android) and Safari (iOS) for camera/mic access
- Mobile-first layout (cook will likely prop up phone in kitchen)

### NFR-4: Audio Quality
- Input: 16-bit PCM at 16kHz mono
- Output: 16-bit PCM at 24kHz (native audio model)
- Agent voice is clear and natural, not robotic

---

## Out of Scope (v1 / Hackathon)

- Multi-language support (English only)
- Multiple concurrent users
- Recipe database / history
- Nutritional information
- Integration with smart kitchen devices
- Image generation overlays (visual coaching arrows)
- Multi-camera support
