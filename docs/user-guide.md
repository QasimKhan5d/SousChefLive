# SousChef Live — User Guide & Demo Playbook

**For anyone demoing or presenting SousChef Live at the Gemini Live Agent Challenge.**

This document is completely self-contained. Read it from top to bottom before your first demo attempt.

---

## Table of Contents

1. [What Is SousChef Live](#1-what-is-souschef-live)
2. [How It Works (Architecture in Plain English)](#2-how-it-works)
3. [What The App Looks Like (UI Walkthrough)](#3-ui-walkthrough)
4. [Every Feature Explained](#4-every-feature-explained)
5. [Pre-Demo Setup](#5-pre-demo-setup)
6. [The 4-Minute Demo Script](#6-the-4-minute-demo-script)
7. [Human Testing Checklist](#7-human-testing-checklist)
8. [Troubleshooting](#8-troubleshooting)
9. [What Judges Are Looking For](#9-what-judges-are-looking-for)
10. [Quick Reference Card](#10-quick-reference-card)

---

## 1. What Is SousChef Live

SousChef Live is a real-time AI sous-chef that **sees your kitchen through your camera**, **hears you and your cooking sounds through your microphone**, and **speaks to you out loud** — all hands-free, in real time. It is not a recipe chatbot. It is a live cooking companion.

You point your phone or laptop camera at your ingredients and cooking, and the chef guides you through the entire process — suggesting recipes, correcting technique, setting timers, and proactively warning you when something looks wrong.

**The pitch in one sentence:** "I cooked a restaurant-quality dish and never touched my phone once — my AI sous-chef watched, listened, and coached me the whole way."

### Why It's Different

| Traditional Recipe Apps | SousChef Live |
|---|---|
| You read instructions on a screen | The chef tells you what to do, out loud |
| You set your own timers | The chef sets timers automatically |
| App doesn't know what's happening | The chef watches your pan and corrects you |
| You stop cooking to scroll | You never touch your phone |
| One-way information | Two-way conversation: you can ask questions, interrupt, and get help |

### The Technology

- **Gemini Live API** — Google's real-time multimodal AI that processes audio and video simultaneously
- **Voice**: Aoede (a calm, natural-sounding voice — not robotic text-to-speech)
- **Model**: `gemini-2.5-flash-native-audio-latest` — native audio generation, multimodal vision, function calling
- **Backend**: Python FastAPI on Google Cloud Run
- **Frontend**: Vanilla JavaScript, WebRTC for camera/mic, Web Audio API for playback

### Hackathon Context

This project is entered in the **Live Agents** category of the Gemini Live Agent Challenge:

> "Build an agent that users can talk to naturally, can be interrupted. Mandatory: Must use Gemini Live API. Hosted on Google Cloud."

SousChef Live satisfies every requirement: real-time voice interaction, vision, interruption handling, proactive behavior, tool use, and Cloud Run deployment.

---

## 2. How It Works

```
┌──────────────────────────────────────────────────────────┐
│  YOUR PHONE / LAPTOP BROWSER                             │
│                                                          │
│  Camera → JPEG frames (1 FPS)  ──┐                      │
│  Microphone → PCM audio (16kHz) ─┤── WebSocket ──────►  │
│  Your voice / text input ────────┘                       │
│                                                          │
│  ◄── Audio playback (24kHz, Aoede voice)                 │
│  ◄── Transcript (what you said + what chef said)         │
│  ◄── UI events (recipe, step, timers, status)            │
└──────────────────────────────────────────────────────────┘
                        │
                   WSS (encrypted)
                        │
┌──────────────────────────────────────────────────────────┐
│  GOOGLE CLOUD RUN (us-central1)                          │
│                                                          │
│  FastAPI WebSocket Server                                │
│  ├── Receives audio + video + text from browser          │
│  ├── Forwards to Gemini Live API                         │
│  ├── Executes tool calls (timers, recipe, step)          │
│  ├── Manages session state + memory                      │
│  └── Sends audio + events back to browser                │
└──────────────────────────────────────────────────────────┘
                        │
                   Gemini API
                        │
┌──────────────────────────────────────────────────────────┐
│  GEMINI LIVE API                                         │
│                                                          │
│  - Processes continuous audio + video                    │
│  - Generates spoken responses (native audio)             │
│  - Detects when you stop speaking (VAD)                  │
│  - Handles interruptions (barge-in)                      │
│  - Calls tools: set_timer, update_recipe, etc.           │
│  - Session resumption + context window compression       │
└──────────────────────────────────────────────────────────┘
```

**Key insight:** The audio between your browser and the server is raw binary (not base64 or JSON-wrapped), which keeps latency low. Video frames are JPEG at 1 frame per second — enough for the chef to see your pan, food, and hands.

---

## 3. UI Walkthrough

### Screen 1: Landing Page

When you first open the app, you see:

- **Title**: "SousChef Live" with the tagline "Your real-time AI sous-chef that sees, hears, and guides you while you cook."
- **Feature badges**: Real-time Voice, Live Vision, Smart Timers
- **Start Cooking button** (red, pulsing) — this is the only button you press
- **Powered by Gemini Live API** badge at the bottom
- Camera and microphone permission note

**Action:** Tap "Start Cooking." The browser asks for camera and microphone permission. Grant both.

### Screen 2: Cooking Screen

Once you start, the screen transitions to the cooking interface:

```
┌──────────────────────────────────────┐
│  [Recipe: --] [Step: Idle] [● Waiting│  ← Status chips (top)
│                  for ingredients]     │
│  ○ LIVE                              │  ← Live indicator
│                                      │
│                                      │
│         YOUR CAMERA FEED             │  ← Full-bleed video background
│       (what the chef sees)           │
│                                      │
│                                      │
│         ┌─────────┐                  │
│         │ 1:45    │                  │  ← Timer card (when active)
│         │sear_s1  │                  │
│         └─────────┘                  │
│                                      │
│  ┌ Chef is speaking ════════════┐    │  ← Speaking indicator + waveform
│                                      │
│  ┌──────────────────────────────┐    │
│  │ ●●●● 420ms │ us-central1 │s_│    │  ← Session badge (deployment proof)
│  │ [■ Stop] [□ Demo 10x]       │    │  ← Controls
│  └──────────────────────────────┘    │
│  ┌ Transcript ──────────────────┐    │
│  │ Y: Chef, I have chicken...  │    │  ← Chat transcript
│  │ C: Great, let's make garlic │    │
│  └──────────────────────────────┘    │
└──────────────────────────────────────┘
```

Every element updates in real time as the chef talks, sets timers, and changes steps.

### UI Elements Explained

| Element | Where | What It Shows |
|---|---|---|
| **Recipe chip** | Top left | Current recipe name (e.g., "Garlic Butter Chicken Thighs") |
| **Step chip** | Top center | Current cooking phase (e.g., "Sear Side 1") |
| **Monitor chip** | Top right | What the chef is watching (e.g., "Watching sear — side 1") |
| **LIVE indicator** | Top right, pulsing red dot | Confirms the session is active |
| **Camera feed** | Full background | Shows what the chef sees — your kitchen |
| **Step progress bar** | Below top bar | Visual progress through cooking steps |
| **Timer cards** | Center-right area | Countdown rings with SVG animation |
| **Speaking indicator** | Center | "Chef is speaking" with audio waveform visualization |
| **Session badge** | Bottom bar | Connection quality bars, RTT latency, region, session ID, active timers |
| **Stop button** | Bottom left | Ends the session and returns to landing page |
| **Demo 10x toggle** | Bottom right | Compresses all timer durations by 10x (for demo) |
| **Transcript panel** | Bottom, collapsible | Chat-bubble transcript — Y (You) and C (Chef) |
| **Error banner** | Top, hidden by default | Shows connection or API errors |
| **Reconnecting overlay** | Full-screen, hidden by default | Spinner overlay if connection drops temporarily |

---

## 4. Every Feature Explained

### 4.1 Natural Voice Conversation

Just talk. The chef hears you through your microphone and responds out loud through your speakers. You never need to type anything.

The chef uses Aoede, a natural-sounding female voice. Responses are short — 1-2 sentences max — because that's how a real sous-chef talks in a busy kitchen.

### 4.2 Interruption / Barge-In

You can interrupt the chef mid-sentence. If the chef is explaining something and you say "Wait, like this?" — the chef stops immediately, answers your question, then optionally resumes.

This is handled by the Gemini Live API's built-in Voice Activity Detection (VAD). When it hears you start speaking, it sends an `interrupted` event, the browser stops audio playback instantly, and the chef addresses your interruption.

### 4.3 Live Vision (Camera Supervision)

The camera sends 1 JPEG frame per second to the chef. The chef can see:
- Your ingredients on the counter
- Your knife technique and hand position
- Pan heat (oil shimmer, smoke)
- Food color and browning
- Cooking actions (flipping, basting)

The chef references what it sees: "I see the garlic is getting dark" or "I'm not seeing shimmer on the oil yet."

### 4.4 Proactive Behavior

The chef does NOT just wait for you to ask questions. It speaks up on its own when it notices:
- **Safety issues**: Unsafe knife grip, fingers too close to blade
- **Timing problems**: Pan not hot enough, food left too long
- **Technique issues**: Overcrowding the pan, moving food too early
- **Encouragement**: "Nice color on that sear"

This is driven by the system instruction — the chef is told: "If you see danger or an obvious mistake, interrupt immediately."

### 4.5 Recipe Generation

Tell the chef what ingredients you have (by voice or by showing them on camera), and it suggests a dish. Example:

> You: "I have chicken thighs, garlic, and butter."
> Chef: "Let's do garlic butter chicken thighs — I'll guide you through it."

The chef then calls the `update_recipe` tool, which sets the recipe name in the UI chip.

### 4.6 Cooking Step Tracking

The chef tracks which phase of cooking you're in:

`idle → prep → heat → sear_side_1 → flip → sear_side_2 → baste → rest → done`

Each transition updates the **Step chip** and **Monitor chip** in the UI. The step progress bar shows visual progress.

### 4.7 Automatic Timers

When a timed step starts (searing, resting), the chef calls `set_timer` automatically without you asking:

> Chef: "Starting a 2-minute sear timer. I'll alert you."

A **timer card** appears with an SVG ring countdown. The timer has two alerts:
- **80% pre-alert**: "45 seconds left — don't move it yet."
- **Expiry alert**: "Time's up — flip now."

These alerts are spoken aloud by the chef. Timer alerts are injected as system messages into the Gemini session, so the chef's voice is the one you always hear.

### 4.8 Demo Speed Mode (10x)

The **Demo 10x** checkbox in the bottom panel compresses all timer durations by 10x. A 2-minute timer becomes 12 seconds. This lets you show the full cooking flow in a 4-minute demo without waiting for real-time timers.

### 4.9 Ingredient Substitution

If you're missing an ingredient, just say so:

> You: "I don't have thyme."
> Chef: "Use rosemary instead — half the amount."

The chef adjusts quantities in the context of the current recipe.

### 4.10 Audio Cue Awareness

The chef listens to cooking sounds:
- **Sizzle intensity**: Indicates pan heat
- **Crackling**: Butter or oil readiness
- **Silence**: Pan not hot enough

> Chef: "The sizzle is weak — the pan needs more time."

### 4.11 Transcript Panel

The collapsible transcript panel at the bottom shows a scrolling conversation history. Each entry has a role label:
- **Y** (You / Cook): What you said
- **C** (Chef): What the chef said

Tap the transcript header to expand or collapse it. It auto-scrolls to the latest message.

### 4.12 Session Memory

The chef remembers the entire conversation within a cooking session. If the connection drops and reconnects:
- The UI is restored to its previous state (recipe, step, timers, transcript)
- The chef is re-primed with a summary of the conversation
- Active timers continue running

The app uses a session memory system with conversation turns, rolling summaries, and structured facts (preferences, substitutions, observations, decisions). Older conversation is automatically compacted to keep the context window bounded.

### 4.13 Connection Quality Indicator

The session badge shows:
- **Signal bars**: Green (< 200ms), yellow (< 500ms), red (> 500ms)
- **RTT**: Round-trip time to the server in milliseconds
- **Region**: `us-central1` (Google Cloud region)
- **Session ID**: Truncated unique identifier proving this is a real session
- **Timer count**: Number of active timers

This is visible proof for judges that the app is deployed on real cloud infrastructure.

### 4.14 Reconnection Handling

If the WebSocket connection drops (network blip, etc.):
1. A **"Reconnecting..."** overlay with a spinner appears
2. The browser retries the connection with the same session ID
3. The server sends a **state hydration snapshot** (recipe, step, timers, transcript)
4. The chef gets a **reconnect primer** with conversation summary
5. The session resumes where it left off

You don't lose your cooking progress.

---

## 5. Pre-Demo Setup

### 5.1 Equipment

- **Phone or laptop** with a working camera and microphone
- **Good lighting** — judges need to see the food. Natural light or a bright kitchen light.
- **Camera angle**: Prop the phone at shoulder height, angled down at the counter/stove. The chef needs to see your hands, the pan, and the food.
- **Audio**: Use the device speakers. If feedback is an issue, use earbuds (one ear in, one out so you can hear real cooking sounds).
- **Stable network**: WiFi, not cellular. The app streams continuous audio and video.

### 5.2 Ingredients (Garlic Butter Chicken Thighs)

Have ready before starting:
- 2-4 bone-in, skin-on chicken thighs
- 4-6 cloves of garlic
- 2 tbsp butter
- Salt and pepper
- Olive oil
- (Optional) fresh thyme or rosemary

Also have nearby:
- A heavy pan (cast iron is ideal)
- Paper towels
- Tongs
- A cutting board and knife

### 5.3 Pre-Flight Checks

1. **Open the app**: `https://souschef-live-504591545979.us-central1.run.app`
2. **Grant permissions**: Camera + microphone (must be HTTPS for this to work)
3. **Verify video**: You should see your camera feed as the full background
4. **Verify audio**: Say "Hello chef" — you should hear a response within 2 seconds
5. **Check session badge**: Should show `us-central1`, an RTT value, and a session ID
6. **Check LIVE indicator**: Should show a pulsing red dot
7. **Test Demo Speed**: Check the "Demo 10x" box — you'll use this during the demo
8. **Pre-cook the dish once** before filming. Know the timing so you're not fumbling during the demo.

### 5.4 Recording Setup (for the submission video)

- **Camera person**: Ideally a friend filming you from shoulder angle with occasional close-ups
- **Screen recording**: If solo, prop the phone running the app where a second camera can see the screen + your cooking
- **Duration**: Must be under 4 minutes
- **Content**: Real cooking, real interaction — no mockups, no pre-recorded responses

---

## 6. The 4-Minute Demo Script

**Dish:** Garlic Butter Chicken Thighs (Pan-Seared, Skin-On)
**Key rule:** Enable "Demo 10x" at the start so timers are compressed.

---

### 0:00–0:15 — Quick Pitch (Talk to Camera)

Camera on you in the kitchen. Ingredients visible behind you.

**You (to camera):**
> "Cooking while staring at your phone is frustrating. SousChef Live is an AI sous-chef that watches, listens, and coaches you hands-free — using Gemini's Live API for continuous voice and vision."

No slides. No screen shares. Just you, the kitchen, and one sentence.

**Why this matters:** Judges immediately know the problem and the solution. This addresses the Demo & Presentation criterion: "Does the video define the problem and solution?"

---

### 0:15–0:30 — Start Cooking (Multimodal Recipe Generation)

Turn to the counter. Camera now shows ingredients + pan + the app on your phone/laptop.

**You (speaking to the chef):**
> "Chef, I want to cook chicken thighs with what I have here."

**Chef (sees ingredients via camera):**
> "I see chicken thighs, garlic, butter. Let's do a quick garlic-butter pan roast."

**What judges see:** Recipe chip updates ("Garlic Butter Chicken Thighs"), step changes to "Prep".

**Why this matters:** Recipe generated in < 15 seconds. Proves multimodal vision + voice.

---

### 0:30–1:10 — Technique Correction (Knife Grip)

Start mincing garlic with an **intentionally poor knife grip** (flat fingers, not curled).

**Chef (proactive, vision-triggered):**
> "Pause — curl your fingertips for safety."

Adjust your grip. Barge in while the chef is talking:

**You:**
> "Like this?"

**Chef stops mid-sentence:**
> "Yes — safer and more control."

**What judges see:**
- Vision-based safety correction (proactive, not asked)
- Barge-in interruption handling (chef stops and responds)

---

### 1:10–2:00 — Pan Readiness (Audio + Visual Cues)

Place pan on stove. Add oil. Drop chicken in when pan is **cold** (intentionally wrong).

**Chef (hearing weak sizzle + seeing no shimmer):**
> "Hold — the sizzle is weak and I'm not seeing shimmer. Wait 20 seconds."

Wait. When pan is ready:

**Chef:**
> "Now place it."

Chicken hits hot pan with a strong sizzle:

**Chef:**
> "Starting a 2-minute sear timer."

**What judges see:**
- Timer card appears automatically (SVG ring countdown)
- Step transitions to "Sear Side 1"
- Chef uses both audio (sizzle) and visual (shimmer) cues
- Timer set proactively (not asked for)

**Note:** Timer will count down in ~12 seconds because Demo 10x is enabled.

---

### 2:00–3:00 — Timer Alert + Barge-In

Timer counts down (fast because of Demo Speed).

**Chef (at 80% mark):**
> "Almost time — don't move it yet."

**You (barge in):**
> "Why not?"

**Chef stops, answers:**
> "Moving breaks the crust. Leave it."

Timer expires:

**Chef:**
> "Flip now."

**What judges see:**
- Async timer monitoring (80% pre-alert + expiry alert)
- Proactive coaching ("don't move it yet" — unsolicited)
- Second barge-in handled cleanly

---

### 3:00–3:50 — Doneness + Rest

Chef observes browning:

**Chef:**
> "Looking golden-brown. Rotate the pan slightly — one side is darker."

You comply.

**Chef:**
> "Great. Rest it 3 minutes. Starting rest timer."

**What judges see:**
- New timer card appears (second timer)
- Step transitions to "Rest"
- Visual doneness assessment
- Multi-timer management

---

### 3:50–4:00 — Punchline

**Chef:**
> "Nice. You just cooked a restaurant-level sear — and you didn't touch your phone once."

Cut.

---

### Demo Speed Summary

With Demo 10x enabled:
- 2-minute sear timer → ~12 seconds
- 3-minute rest timer → ~18 seconds
- Total real time fits comfortably in 4 minutes

---

## 7. Human Testing Checklist

Before recording the final demo, run through each of these manually. Check the box when you've verified it works.

### Voice Interaction
- [ ] Say something — get a spoken response within ~2 seconds
- [ ] Interrupt the chef mid-sentence — playback stops immediately
- [ ] Ask a follow-up after interrupting — chef answers the new question
- [ ] Speak for a long sentence — chef waits until you finish before responding
- [ ] Stay silent for 10 seconds — no audio glitches or disconnects

### Vision
- [ ] Show ingredients on camera — chef references what it sees
- [ ] Do something with poor technique — chef corrects you proactively
- [ ] Move camera to something new — chef adapts commentary
- [ ] Cover the camera — chef says it can't see clearly (or falls back to audio)

### Timers
- [ ] Chef sets a timer automatically during a timed step
- [ ] Timer card appears in the UI with countdown ring
- [ ] 80% pre-alert fires ("almost time")
- [ ] Expiry alert fires ("time's up")
- [ ] Demo Speed checkbox makes timers 10x faster
- [ ] Multiple timers can run simultaneously

### Cooking State
- [ ] Recipe chip updates when chef names a dish
- [ ] Step chip updates as cooking progresses
- [ ] Monitor chip shows relevant observation text
- [ ] Progress bar advances with each step

### Transcript
- [ ] Your speech appears as "Y" entries
- [ ] Chef speech appears as "C" entries
- [ ] Transcript auto-scrolls to latest message
- [ ] Tap transcript header to expand/collapse

### Session Quality
- [ ] Session badge shows region (`us-central1`)
- [ ] RTT shows a realistic latency value
- [ ] LIVE indicator pulses red
- [ ] Signal bars show quality level

### Substitution
- [ ] Say "I don't have [ingredient]" — chef suggests alternative
- [ ] Chef adjusts quantity in the suggestion

### Reconnection (optional, advanced)
- [ ] Briefly disable WiFi, re-enable — reconnecting overlay appears
- [ ] After reconnect, recipe/step/timers are restored
- [ ] Chef continues with awareness of prior conversation

### End Session
- [ ] Press Stop — returns to landing page
- [ ] Camera and microphone stop streaming
- [ ] Session is cleaned up

---

## 8. Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| "Start Cooking" doesn't work | Browser blocked camera/mic | Check permissions in browser settings. Must be HTTPS. |
| No chef audio response | WebSocket didn't connect | Check network. Reload the page. Try again. |
| Audio feedback loop | Speaker audio feeding back into mic | Use earbuds or increase physical separation |
| Chef says nothing proactive | System instruction didn't reach the model | This is LLM non-determinism — try saying "What do you see right now?" to prompt vision |
| Timer doesn't appear | Chef answered verbally instead of calling the tool | LLM non-determinism — say "Can you set a timer for 2 minutes?" |
| Video is black | Camera permission denied or no camera available | Re-grant camera permissions |
| High latency (> 2s response time) | Network congestion or Cloud Run cold start | Wait 30 seconds for warm-up. Check WiFi. |
| "Reconnecting..." stuck | Server crashed or network fully down | Reload the page. Session state may be lost. |
| Demo Speed not working | Checkbox wasn't sent to server | Toggle it off and on again while connected |

---

## 9. What Judges Are Looking For

### Innovation (40% of score)

What matters:
- Continuous multimodal input (video + audio streaming — not one-shot)
- Proactive behavior (chef speaks up without being asked)
- Async timer orchestration (automatic, with pre-alerts)
- Safety intervention (knife grip correction)
- Observational honesty ("I'm not seeing shimmer" — not fake precision)

### Demo & Presentation (30% of score)

What matters:
- Clear story arc: ingredients → guidance → correction → completion
- Live proof visible in the UI (session badge, RTT, timers)
- No dead time (every second has purpose)
- Natural interaction (not scripted-feeling)

### Other Criteria

- **Gemini usage**: Must use Gemini Live API — we do (native audio, multimodal, function calling)
- **Google Cloud**: Must host on Google Cloud — we do (Cloud Run, us-central1)
- **Reproducible**: Must have README + setup instructions — we do
- **Deployment proof**: Separate recording showing Cloud Run console, logs, health endpoint

### What To Avoid

- Standing still waiting for AI to respond
- Long silent gaps (> 3 seconds)
- Chef rambling (> 2 sentences per turn)
- Only reacting after you ask (must show proactive behavior)
- Scripted, unnatural feel
- Fake perfection — make one visible mistake so the chef can correct it

---

## 10. Quick Reference Card

Print or screenshot this for the demo.

```
URL:     https://souschef-live-504591545979.us-central1.run.app
Model:   gemini-2.5-flash-native-audio-latest
Voice:   Aoede
Region:  us-central1 (Cloud Run)

DEMO FLOW (4 min):
  0:00  Pitch to camera (1 sentence: problem + solution)
  0:15  Show ingredients, ask chef what to cook
  0:30  Mince garlic with bad grip → chef corrects
  1:10  Cold pan → chef says wait for shimmer
  2:00  Timer pre-alert → barge in → chef answers
  3:00  Doneness check → rest timer
  3:50  Punchline: "never touched your phone"

CONTROLS:
  [Start Cooking]  — begins session
  [Stop]           — ends session
  [Demo 10x]       — compresses timers

TIPS:
  - Enable Demo 10x FIRST
  - Make one deliberate mistake (bad knife grip or cold pan)
  - Interrupt at least once to show barge-in
  - Keep hands visible to camera at all times
  - Good lighting is critical

IF SOMETHING GOES WRONG:
  - Say "What do you see?" to trigger vision response
  - Say "Set a 2-minute timer" if chef doesn't auto-set
  - Reload page if connection drops
  - Stay calm — judges value recovery, not perfection
```

---

## Separate Submission: Deployment Proof

This is NOT part of the 4-minute demo. The hackathon accepts two options:

**Option A — Link to code file (easiest, recommended):**
Link to `scripts/deploy.sh` in your public GitHub repo. This is an automated `gcloud run deploy` script that proves Google Cloud usage. It also earns the bonus points for "automated cloud deployment." No recording needed.

**Option B — Screen recording (stronger, optional):**
A 1-2 minute recording showing:
1. Cloud Run console → `souschef-live` service running in `us-central1`
2. Environment variables configured (GEMINI_API_KEY, MODEL)
3. Cloud Run logs streaming structured events
4. Health endpoint: `https://souschef-live-504591545979.us-central1.run.app/api/health`

**In-app proof (passive, no action needed):**
The session badge in the cooking screen already shows `us-central1`, RTT latency, and session ID throughout the demo — judges see this without any infrastructure screen-switching.

---

## Submission Checklist

Before submitting to Devpost:

- [ ] 4-minute demo video uploaded (real cooking, no mockups)
- [ ] Deployment proof recording uploaded (Cloud Run console + logs)
- [ ] GitHub repo is public with:
  - [ ] README with setup instructions
  - [ ] `requirements.txt` with dependencies
  - [ ] `scripts/deploy.sh` for automated deployment (bonus points)
  - [ ] Architecture diagram in docs or README
- [ ] Text description covering: features, technologies, learnings
- [ ] (Bonus) Blog post / social content with #GeminiLiveAgentChallenge
- [ ] (Bonus) GDG profile link
