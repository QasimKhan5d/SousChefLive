#!/usr/bin/env python3
"""
Test the 4-minute demo flow from docs/user-guide.md as much as possible without real voice/camera.

Runs through the demo script programmatically and verifies:
- Recipe generation (ingredients + voice)
- Knife grip correction (poor_knife_grip image)
- Cold pan guidance (cold_pan_oil image)
- Timer setup (chicken_searing + request)
- Timer milestones (pre-alert, expiry) with Demo 10x
- Doneness assessment (golden_brown_sear)
- Ingredient substitution

Usage: set -a && source .env && set +a && python scripts/test_demo_flow.py
"""

import asyncio
import base64
import json
import os
import ssl
import time
from pathlib import Path

import websockets

URL = os.environ.get(
    "DEPLOYED_URL",
    "https://souschef-live-5z4a6smnda-uc.a.run.app",
).replace("https://", "wss://").replace("http://", "ws://")
FIXTURES = Path(__file__).resolve().parent.parent / "harness" / "fixtures" / "images"


def img_b64(name: str) -> str:
    return base64.b64encode((FIXTURES / name).read_bytes()).decode()


def setup_msg():
    return json.dumps({
        "setup": {
            "generation_config": {"response_modalities": ["AUDIO"]},
            "input_audio_transcription": {},
            "output_audio_transcription": {},
        }
    })


def text_msg(t: str):
    return json.dumps({"type": "text", "text": t})


def control_msg(action: str, value=True):
    return json.dumps({"type": "control", "action": action, "value": value})


async def collect_until_turn(ws, timeout_s=50, drain_after_turn_s=3.0):
    """Collect events until turnComplete, then drain briefly for trailing outputTranscription."""
    events = []
    deadline = time.time() + timeout_s
    turn_complete_seen = False
    drain_deadline = None
    while time.time() < deadline:
        if drain_deadline and time.time() > drain_deadline:
            break
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=8)
        except asyncio.TimeoutError:
            if turn_complete_seen and drain_deadline:
                break
            continue
        if isinstance(msg, bytes):
            events.append({"_t": "audio"})
            continue
        d = json.loads(msg)
        events.append(d)
        if d.get("serverContent", {}).get("turnComplete"):
            turn_complete_seen = True
            drain_deadline = time.time() + drain_after_turn_s
    return events


def extract_output(events):
    # Gemini sends cumulative outputTranscription; use the last one
    last = ""
    for e in events:
        t = e.get("serverContent", {}).get("outputTranscription", {}).get("text")
        if t:
            last = t
    return last.strip()


def extract_tools(events):
    return [e for e in events if e.get("type") == "tool_call"]


def extract_proactive(events):
    return [e for e in events if e.get("type") == "proactive_meta"]


def extract_state(events):
    for e in reversed(events):
        if e.get("type") == "state_update":
            return e
    return None


async def run():
    ssl_ctx = ssl.create_default_context()
    sid = f"demo_test_{int(time.time())}"
    uri = f"{URL}/ws?session_id={sid}"
    results = []

    async with websockets.connect(uri, ssl=ssl_ctx, open_timeout=15) as ws:
        await ws.send(setup_msg())
        await asyncio.sleep(1)

        # Enable Demo 10x FIRST (per user guide)
        await ws.send(control_msg("demo_speed", True))
        await asyncio.sleep(0.5)

        # === 0:15–0:30 — Recipe generation ===
        print("\n=== DEMO STEP: Recipe generation (ingredients + voice) ===")
        await ws.send(json.dumps({"type": "image", "data": img_b64("garlic_butter_ingredients.jpg"), "mimeType": "image/jpeg"}))
        await ws.send(text_msg("Chef, I want to cook chicken thighs with what I have here."))
        ev1 = await collect_until_turn(ws, 45)
        out1 = extract_output(ev1)
        tools1 = extract_tools(ev1)
        state1 = extract_state(ev1)
        recipe_set = any(t.get("name") == "update_recipe" for t in tools1)
        step_prep = state1 and state1.get("current_step") == "prep"
        has_garlic_chicken = "garlic" in out1.lower() and "chicken" in out1.lower()
        results.append(("Recipe generation", {
            "recipe_tool_called": recipe_set,
            "step_prep": step_prep,
            "mentions_dish": has_garlic_chicken,
            "output_preview": out1[:150] + "..." if len(out1) > 150 else out1,
        }))
        print(f"  update_recipe: {recipe_set}, step=prep: {step_prep}, mentions dish: {has_garlic_chicken}")
        print(f"  events: {len(ev1)}, audio: {sum(1 for e in ev1 if e.get('_t')=='audio')}, tools: {[t.get('name') for t in tools1]}")
        print(f"  Chef: {out1[:200]}...")
        await asyncio.sleep(3)

        # === 0:30–1:10 — Knife grip correction ===
        print("\n=== DEMO STEP: Knife grip (poor technique) ===")
        await ws.send(json.dumps({"type": "image", "data": img_b64("poor_knife_grip.jpg"), "mimeType": "image/jpeg"}))
        await ws.send(text_msg("Mincing the garlic now. How does my technique look?"))
        ev2 = await collect_until_turn(ws, 45)
        out2 = extract_output(ev2)
        safety_keywords = ["finger", "curl", "grip", "safe", "blade", "hand", "careful", "pause"]
        has_safety = any(kw in out2.lower() for kw in safety_keywords)
        results.append(("Knife grip", {
            "safety_guidance": has_safety,
            "output_preview": out2[:150] + "..." if len(out2) > 150 else out2,
        }))
        print(f"  Safety guidance: {has_safety}")
        print(f"  Chef: {out2[:200]}...")
        await asyncio.sleep(3)

        # === 1:10–2:00 — Cold pan ===
        print("\n=== DEMO STEP: Cold pan (wait for shimmer) ===")
        await ws.send(json.dumps({"type": "image", "data": img_b64("cold_pan_oil.jpg"), "mimeType": "image/jpeg"}))
        await ws.send(text_msg("I'm about to put the chicken in the pan. Ready?"))
        ev3 = await collect_until_turn(ws, 45)
        out3 = extract_output(ev3)
        heat_keywords = ["shimmer", "heat", "wait", "hot", "ready", "warm"]
        has_heat_guidance = any(kw in out3.lower() for kw in heat_keywords)
        results.append(("Cold pan", {
            "heat_guidance": has_heat_guidance,
            "output_preview": out3[:150] + "..." if len(out3) > 150 else out3,
        }))
        print(f"  Heat guidance: {has_heat_guidance}")
        print(f"  events: {len(ev3)}, audio: {sum(1 for e in ev3 if e.get('_t')=='audio')}")
        print(f"  Chef: {out3[:200] if out3 else '(no output)'}...")
        await asyncio.sleep(3)

        # === 2:00 — Request timer (chef should set it) ===
        print("\n=== DEMO STEP: Timer setup (sear) ===")
        await ws.send(json.dumps({"type": "image", "data": img_b64("chicken_searing.jpg"), "mimeType": "image/jpeg"}))
        await ws.send(text_msg("The chicken just went in. Nice sizzle! Start a 2-minute sear timer."))
        ev4 = await collect_until_turn(ws, 45)
        tools4 = extract_tools(ev4)
        timer_set = any(t.get("name") == "set_timer" for t in tools4)
        step_sear = any(extract_state(ev4) and extract_state(ev4).get("current_step") == "sear_side_1" for _ in [1])
        state4 = extract_state(ev4)
        step_sear = state4 and state4.get("current_step") == "sear_side_1"
        out4 = extract_output(ev4)
        results.append(("Timer setup", {
            "set_timer_called": timer_set,
            "step_sear": step_sear,
            "output_preview": out4[:150] if out4 else "",
        }))
        print(f"  set_timer: {timer_set}, step=sear_side_1: {step_sear}")
        print(f"  events: {len(ev4)}, tools: {[t.get('name') for t in tools4]}")
        print(f"  Chef: {out4[:200] if out4 else '(no output)'}...")
        await asyncio.sleep(3)

        # === Wait for timer milestones (Demo 10x: 2min -> 12s, prealert at ~9.6s) ===
        print("\n=== DEMO STEP: Timer milestones (pre-alert + expiry) ===")
        window = []
        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
            except asyncio.TimeoutError:
                continue
            if isinstance(msg, bytes):
                window.append({"_t": "audio"})
            else:
                window.append(json.loads(msg))
        proactive = extract_proactive(window)
        out_window = extract_output(window)
        timer_meta = [p for p in proactive if p.get("reason_code") in {"timer_prealert", "timer_expired"}]
        out_lower = out_window.lower()
        has_timer_speech = any(
            kw in out_lower for kw in ["timer", "flip", "second", "time", "up", "alert", "almost", "don't move"]
        )
        audio_count = sum(1 for e in window if e.get("_t") == "audio")
        # Pass if we have timer events + audio (speech may not transcribe reliably)
        timer_ok = len(timer_meta) >= 2 and (has_timer_speech or audio_count >= 20)
        results.append(("Timer milestones", {
            "timer_ok": timer_ok,
            "proactive_meta": len(timer_meta),
            "timer_speech_seen": str(has_timer_speech),
            "audio_chunks": audio_count,
        }))
        print(f"  proactive_meta (timer): {len(timer_meta)}, timer speech: {has_timer_speech}, timer_ok: {timer_ok}")
        await asyncio.sleep(5)  # Let model settle before doneness

        # === 3:00–3:50 — Doneness ===
        print("\n=== DEMO STEP: Doneness (golden sear) ===")
        await ws.send(json.dumps({"type": "image", "data": img_b64("golden_brown_sear.jpg"), "mimeType": "image/jpeg"}))
        await ws.send(text_msg("Chef, how does this browning look? Ready to flip?"))
        ev5 = await collect_until_turn(ws, 45)
        out5 = extract_output(ev5)
        positive_keywords = ["good", "great", "nice", "perfect", "golden", "brown", "looks", "flip", "ready", "done", "rest", "plate", "color"]
        has_positive = any(kw in out5.lower() for kw in positive_keywords)
        results.append(("Doneness", {
            "positive_assessment": has_positive,
            "output_preview": out5[:150] + "..." if len(out5) > 150 else out5,
        }))
        print(f"  Positive assessment: {has_positive}")
        print(f"  Chef: {out5[:200]}...")
        await asyncio.sleep(8)  # Let doneness fully complete before substitution

        # === Substitution ===
        print("\n=== DEMO STEP: Ingredient substitution ===")
        await ws.send(text_msg("For the garlic butter chicken we're making, I don't have thyme. What herb can I use instead?"))
        ev6 = await collect_until_turn(ws, 45)
        out6 = extract_output(ev6)
        sub_keywords = ["rosemary", "oregano", "parsley", "marjoram", "basil", "herb", "instead", "alternative", "substitute", "use", "skip", "optional", "omit", "half", "amount"]
        has_sub = any(kw in out6.lower() for kw in sub_keywords)
        results.append(("Substitution", {
            "suggests_alternative": has_sub,
            "output_preview": out6[:150] + "..." if len(out6) > 150 else out6,
        }))
        print(f"  Suggests alternative: {has_sub}")
        print(f"  Chef: {out6[:200]}...")

    # Summary
    print("\n" + "=" * 60)
    print("DEMO FLOW TEST SUMMARY")
    print("=" * 60)
    for name, r in results:
        passed = all(v for k, v in r.items() if isinstance(v, bool))
        status = "PASS" if passed else "CHECK"
        print(f"  {status} {name}: {r}")
    return results


if __name__ == "__main__":
    asyncio.run(run())
