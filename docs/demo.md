# SousChef Live — Final Demo Plan

**Duration:** 4 minutes  
**Dish:** Garlic Butter Chicken Thighs (Pan-Seared, Skin-On)  
**Camera:** Friend filming, shoulder-angle with close-ups  
**Deployed at:** `souschef-live-504591545979.us-central1.run.app`

---

## What Judges Must Feel

- It **sees** (video analysis of pan, food, technique).
- It **listens** (sizzle detection, voice interruption handling).
- It **speaks proactively** (doesn't wait to be asked).
- It **monitors asynchronously** (timers fire independently).
- It's **deployed on Google Cloud** (session badge, RTT indicator prove it).
- It uses **Gemini Live multimodal** (continuous audio+video, not chat).

---

## Demo Timeline

### 0:00–0:15 — Quick Pitch (Talk to Camera)

Camera on you in the kitchen. Ingredients visible behind you.

You (to camera):
> "Cooking while staring at your phone is frustrating. SousChef Live is an AI sous-chef that watches, listens, and coaches you hands-free — using Gemini's Live API for continuous voice and vision."

**No slides. No screen shares. Just you, the kitchen, and one sentence.**

**Goal:** Judges immediately know the problem (phone-bound cooking) and the solution (live multimodal coaching).

---

### 0:15–0:30 — Start Cooking (Multimodal Recipe Generation)

Turn to the counter. Camera now shows ingredients + pan + the app on your phone/laptop.

You (speaking to the chef):
> "Chef, I want to cook chicken thighs with what I have here."

Agent (sees ingredients via video):
> "I see chicken thighs, garlic, butter. Let's do a quick garlic-butter pan roast. I'll guide you live."

UI updates: recipe chip appears ("Garlic Butter Chicken Thighs"), step transitions to `prep`.

**Goal:** Recipe generation in under 15 seconds. Judges see multimodal vision + voice.

---

### 0:30–1:10 — Technique Correction (Knife Grip + Safety)

You start mincing garlic with intentionally poor knife grip.

Agent (proactive, vision-triggered):
> "Pause — curl your fingertips for safety."

You adjust and ask (barge-in):
> "Like this?"

Agent stops mid-response, answers:
> "Yes — safer and more control."

**Demonstrates:**
- Vision analysis (sees hands)
- Proactive safety intervention
- Barge-in / interruption handling

---

### 1:10–2:00 — Pan Readiness (Honest Observational Reasoning)

You add oil and drop chicken in when pan is cold. Weak sizzle.

Agent (audio + video cue):
> "Hold — sizzle is weak and I'm not seeing shimmer yet. Wait 20 seconds."

Then:
> "Okay, now place it."

As soon as chicken hits hot pan:
> "Starting a 2-minute sear timer."

UI: Timer card appears automatically. Step transitions to `sear_side_1`.

**Demonstrates:**
- Audio cue detection (sizzle intensity)
- Visual cue detection (oil shimmer)
- Honest observational claims (not fake precision)
- Proactive timer (agent-initiated, not user-requested)

---

### 2:00–3:00 — Proactive Timer Alert + Barge-In

Timer counts down (compress with Demo Speed toggle if needed).

At 80% mark, agent:
> "45 seconds left — don't move it yet."

You barge in:
> "Why not move it?"

Agent stops and answers:
> "Moving breaks crust formation. Leave it."

Timer expires:
> "Flip now."

UI: Step transitions to `flip`, then `sear_side_2`.

**Demonstrates:**
- Async timer monitoring (80% pre-alert + expiry alert)
- Proactive coaching (unsolicited guidance)
- Barge-in handling (stops, answers, resumes)

---

### 3:00–3:50 — Doneness Guidance + Rest

Agent observes browning:
> "You're aiming for golden-brown. I'm seeing one edge darker — rotate the pan slightly."

You comply.

Agent:
> "Great. Rest it 3 minutes. Starting rest timer."

UI: New timer card appears. Step transitions to `rest`.

**Demonstrates:**
- Visual doneness assessment
- Multi-timer management
- Continued proactive behavior

---

### 3:50–4:00 — Punchline

Agent:
> "Nice. You just cooked a restaurant-level sear — and you didn't touch your phone once."

Cut.

---

## UI Proof Signals (Visible Throughout Demo)

These elements are always visible in the product UI, subtly proving real deployment:

1. **Session badge:** `us-central1 | Cloud Run`
2. **RTT indicator:** `RTT: 420ms`
3. **Timer badge:** `Timers: 1 active`
4. **Step chip:** Current cooking phase
5. **Monitoring status:** "Watching sear — side 1"
6. **Recipe name:** "Garlic Butter Chicken Thighs"

No architecture slides needed. The product itself proves deployment.

---

## Scoring Alignment

### Innovation & Multimodal UX (40%)
- Breaks the "text box" paradigm — cook never touches phone
- See: continuous camera vision (ingredient ID, technique, browning)
- Hear: voice + cooking sound awareness (sizzle intensity)
- Speak: proactive intervention (agent initiates, not just responds)
- Distinct persona: calm sous-chef character via Aoede voice
- Live + context-aware: stateful cooking flow, not disjointed turns
- Async timer orchestration (80% pre-alert + expiry)
- Observational honesty (no fake precision claims)

### Technical Implementation (30%)
- google-genai SDK with Gemini Live API (bidi streaming, native audio)
- Cloud Run deployment (us-central1, session affinity, 3600s timeout)
- 4 function-calling tools: update_recipe, set_timer, update_cooking_step, get_cooking_state
- Error handling: reconnect with state hydration, session resumption handles
- Grounding: agent describes observations ("I'm not seeing shimmer") not measurements
- No hallucination: agent is instructed to be observational, never claims false precision

### Demo & Presentation (30%)
- Pitch in first 15 seconds: defines problem (phone-bound cooking) and solution
- Architecture diagram in repo + Devpost image carousel
- Cloud deployment proof: separate recording OR link to `scripts/deploy.sh`
- Session badge (us-central1, RTT, session ID) visible throughout demo as passive proof
- Actual software working live — no mockups, no pre-recorded responses
- Clear story arc (ingredients → guidance → correction → completion)

---

## Critical Rules

1. Keep corrections short — long AI speech kills immersion.
2. Don't fake perfection — make one visible mistake before correction.
3. Keep latency under ~1.5s.
4. Lighting must be good — judges need to see food clearly.
5. Pre-cook the dish once before filming to know timing.

## What to Avoid

- Standing still waiting for AI
- 10-second silent latency gaps
- AI rambling (>2 sentences per turn)
- Only reacting after user asks (must be proactive)
- Scripted feel

---

## Separate Submission: Google Cloud Deployment Proof

**Not part of the 4-minute demo.** The hackathon accepts two options:

### Option A: Link to code file (easiest)
Link to `scripts/deploy.sh` in the public repo. This is an automated Cloud Run deployment script using `gcloud run deploy` with infrastructure-as-code configuration. This simultaneously satisfies the deployment proof requirement AND the bonus points for automated deployment.

### Option B: Screen recording (stronger but optional)
A 1-2 minute recording showing:
1. Cloud Run console → service running
2. Environment variables (GEMINI_API_KEY set)
3. Cloud Run logs streaming
4. Health endpoint responding

See `docs/deployment-proof-plan.md` for details.

### In the demo itself
The session badge (`us-central1`, RTT, session ID) is always visible in the product UI during the demo — this provides passive visual proof without needing to switch to infrastructure screens.

---

## Pre-Demo Checklist

See `scripts/harness/demo-checklist.md` for the full preparation and execution checklist.
