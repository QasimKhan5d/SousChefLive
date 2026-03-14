# SousChef Live — Demo Checklist

Use this checklist before recording the 4-minute demo and the separate
Google Cloud deployment proof video.

## Pre-Demo Setup

- [ ] Headphones plugged in (prevents audio feedback loop)
- [ ] Good lighting, camera angle shows hands + pan clearly
- [ ] Stable network connection (wired preferred)
- [ ] Chrome or Safari with camera/mic permissions pre-granted
- [ ] Demo speed toggle visible and ready
- [ ] Ingredients laid out: chicken thighs, garlic, butter, pan, tongs

## 4-Minute Demo — Must-Hit Beats

| # | Beat | Time Target | What to Show |
|---|------|-------------|--------------|
| 1 | Recipe suggestion | 0:00–0:30 | Say ingredients → agent suggests recipe |
| 2 | Cook mode transition | 0:30–0:45 | UI updates: recipe name, step chip → "prep" |
| 3 | Proactive visual correction | 0:45–1:30 | Show hands/knife → agent corrects technique |
| 4 | Proactive sear timer | 1:30–2:00 | Place chicken in pan → agent calls set_timer → timer card appears |
| 5 | Barge-in interruption | 2:00–2:30 | Interrupt agent mid-sentence → audio stops immediately |
| 6 | Flip/rest alert | 2:30–3:30 | Timer pre-alert and expiry fire → agent says "flip now" |
| 7 | Session badge + proof | 3:30–4:00 | Show session badge: region, RTT, timer count |

## Judge-Facing Proof Elements

- [ ] Session badge visible throughout demo (session ID, region, RTT)
- [ ] Active timer count displayed in badge area
- [ ] Timer card with countdown visible
- [ ] Step chip shows progression (idle → prep → heat → sear_side_1 → flip)
- [ ] Monitoring status updates live
- [ ] Transcript panel shows both cook and chef speech

## Failure Mitigations

- [ ] If agent is not proactive: manually describe what you see ("I'm putting chicken in the pan now")
- [ ] If timer doesn't appear: say "set a 2-minute timer for the sear"
- [ ] If audio cuts out: check session badge for disconnect, reload page
- [ ] If latency > 3s: mention demo speed toggle, verify network

## Google Cloud Deployment Proof (Separate Recording)

- [ ] Show Cloud Run console: service `souschef-live` running in `europe-west1`
- [ ] Show service details: min-instances=1, session affinity enabled
- [ ] Show environment variables (mask the API key value)
- [ ] Show logs streaming in Cloud Run logs explorer
- [ ] Open deployed URL on phone/browser
- [ ] Complete a brief cooking interaction on deployed infra
- [ ] Show session badge confirming `europe-west1 | Cloud Run`

## Post-Demo Validation

- [ ] Demo video is under 4 minutes
- [ ] Audio is clear (no echo, no clipping)
- [ ] All 7 beats were hit
- [ ] Deployment proof video is separate and clear
