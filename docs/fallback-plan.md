# SousChef Live — Fallback Plan

Contingency plans for demo and deployment failures.

---

## 1. Agent Not Proactive Enough

**Symptoms**: Agent waits for explicit requests instead of volunteering timers or safety corrections.

**Mitigations**:
1. Narrate what you're doing: "I'm putting the chicken in the pan now" — this gives the model visual + audio context to trigger proactive behavior.
2. If timer doesn't appear: say "Can you set a 2-minute timer for the sear?"
3. If no safety correction: deliberately show bad knife technique or move pan handle over burner.
4. System instruction already includes proactivity rules; if the model is still passive, increase the `proactiveAudio` emphasis in the prompt.

## 2. Audio Issues

**Symptoms**: Echo loop, no audio output, garbled playback.

**Mitigations**:
1. Always use headphones during demo (prevents feedback loop).
2. If no audio: check session badge for disconnect indicator, reload.
3. If garbled: verify sample rate (16kHz in / 24kHz out) matches.
4. Fallback: transcript panel provides visual confirmation the agent is responding.

## 3. High Latency (> 3s)

**Symptoms**: Noticeable delay between speaking and agent response.

**Mitigations**:
1. Use wired network connection for demo.
2. Enable demo speed to compress timer durations.
3. Choose a time of day with lower API load.
4. If persistent: mention in demo that latency depends on API load and show the RTT metric in session badge.

## 4. WebSocket Disconnection

**Symptoms**: Session drops mid-demo.

**Mitigations**:
1. Auto-reconnect with exponential backoff is built in.
2. Reconnect primer restores recipe + step + timers.
3. If auto-reconnect fails: click Start again; session badge will show new connection.
4. Show the reconnect as a feature: "The app handles disconnects gracefully."

## 5. Camera/Mic Permission Denied

**Symptoms**: Browser blocks media access.

**Mitigations**:
1. Pre-grant permissions before recording demo.
2. If denied: app stays on permission screen with clear instructions.
3. Text-only mode: the agent can still function via text input (not ideal for demo).

## 6. Cloud Run Cold Start

**Symptoms**: First request takes 10+ seconds.

**Mitigations**:
1. Deploy with `min-instances=1` to keep one instance warm.
2. Hit the health endpoint before starting the demo.
3. If cold start happens during demo: explain it and show the RTT improving.

## 7. API Quota or Billing Issues

**Symptoms**: 429 or 403 errors from Gemini API.

**Mitigations**:
1. Verify credits before demo (currently have €254 free credits).
2. Keep demo sessions short (< 5 minutes).
3. Have a backup API key if possible.
4. If quota exceeded: show the local fake mode as a demonstration of the architecture.

## 8. Deployment Failure

**Symptoms**: `scripts/deploy.sh` fails or Cloud Run service unhealthy.

**Mitigations**:
1. Run deploy script at least 24 hours before deadline.
2. Keep a working local deployment as backup.
3. Capture Cloud Run console screenshots for proof even if live demo fails.
4. Use deploy-smoke.sh to validate before demo.
