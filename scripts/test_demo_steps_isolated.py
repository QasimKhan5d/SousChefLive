#!/usr/bin/env python3
"""
Run each demo step in isolation (fresh session) to verify it works.
"""
import asyncio
import base64
import json
import os
import ssl
import time
from pathlib import Path
import websockets

URL = os.environ.get("DEPLOYED_URL", "https://souschef-live-5z4a6smnda-uc.a.run.app")
URL = URL.replace("https://", "wss://").replace("http://", "ws://")
FIXTURES = Path(__file__).resolve().parent.parent / "harness" / "fixtures" / "images"


async def run_step(name, steps, timeout_s=55):
    """Run a single demo step with fresh connection."""
    ssl_ctx = ssl.create_default_context()
    sid = f"demo_{name}_{int(time.time())}"
    uri = f"{URL}/ws?session_id={sid}"
    events = []
    async with websockets.connect(uri, ssl=ssl_ctx, open_timeout=15) as ws:
        await ws.send(json.dumps({
            "setup": {"generation_config": {"response_modalities": ["AUDIO"]},
                      "input_audio_transcription": {}, "output_audio_transcription": {}},
        }))
        await asyncio.sleep(1)
        if ("demo_speed", True) in steps:
            await ws.send(json.dumps({"type": "control", "action": "demo_speed", "value": True}))
            await asyncio.sleep(0.3)
        for step in steps:
            if step[0] == "image":
                b64 = base64.b64encode((FIXTURES / step[1]).read_bytes()).decode()
                await ws.send(json.dumps({"type": "image", "data": b64, "mimeType": "image/jpeg"}))
            elif step[0] == "text":
                await ws.send(json.dumps({"type": "text", "text": step[1]}))
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=8)
            except asyncio.TimeoutError:
                continue
            if isinstance(msg, bytes):
                events.append({"_t": "audio"})
            else:
                d = json.loads(msg)
                events.append(d)
                if d.get("serverContent", {}).get("turnComplete"):
                    break
    out = ""
    for e in reversed(events):
        t = e.get("serverContent", {}).get("outputTranscription", {}).get("text")
        if t:
            out = t
            break
    tools = [e for e in events if e.get("type") == "tool_call"]
    return {"name": name, "events": len(events), "audio": sum(1 for e in events if e.get("_t") == "audio"),
            "output": out.strip(), "tools": [t.get("name") for t in tools]}


async def main():
    steps = [
        ("Recipe", [("demo_speed", True), ("image", "garlic_butter_ingredients.jpg"),
         ("text", "Chef, I want to cook chicken thighs with what I have here.")]),
        ("Knife grip", [("image", "poor_knife_grip.jpg"), ("text", "Mincing the garlic now.")]),
        ("Cold pan", [("image", "cold_pan_oil.jpg"), ("text", "I'm about to put the chicken in. Ready?")]),
        ("Timer", [("demo_speed", True), ("image", "chicken_searing.jpg"),
         ("text", "Chicken just went in. Start a 2-minute sear timer please.")]),
        ("Doneness", [("image", "golden_brown_sear.jpg"), ("text", "How does this side look?")]),
        ("Substitution", [("text", "I don't have thyme. What can I use instead?")]),
    ]
    print("Running each demo step in isolation (fresh session per step)...\n")
    for name, step_list in steps:
        r = await run_step(name, step_list)
        print(f"=== {r['name']} ===")
        print(f"  events: {r['events']}, audio: {r['audio']}, tools: {r['tools']}")
        print(f"  Chef: {r['output'][:250] if r['output'] else '(none)'}...")
        # Semantic checks
        if r["name"] == "Recipe":
            ok = ("garlic" in r["output"].lower() and "chicken" in r["output"].lower()) or "update_recipe" in r["tools"]
            print(f"  PASS: {ok}")
        elif r["name"] == "Knife grip":
            ok = any(k in r["output"].lower() for k in ["finger", "curl", "grip", "safe", "blade"])
            print(f"  Safety guidance: {ok}")
        elif r["name"] == "Cold pan":
            ok = any(k in r["output"].lower() for k in ["shimmer", "heat", "wait", "hot"])
            print(f"  Heat guidance: {ok}")
        elif r["name"] == "Timer":
            ok = "set_timer" in r["tools"]
            print(f"  Timer set: {ok}")
        elif r["name"] == "Doneness":
            ok = any(k in r["output"].lower() for k in ["good", "great", "nice", "golden", "brown"])
            print(f"  Positive: {ok}")
        elif r["name"] == "Substitution":
            ok = any(k in r["output"].lower() for k in ["rosemary", "oregano", "instead", "alternative"])
            print(f"  Suggests alt: {ok}")
        print()
        await asyncio.sleep(5)  # Pause between sessions to avoid rate limits


if __name__ == "__main__":
    asyncio.run(main())
