"""Demo rehearsal test — simulates the full 4-minute demo flow against
the live deployed service and captures every event for qualitative analysis.

This is NOT a pass/fail unit test. It's a diagnostic that dumps rich output
so an operator can verify:
  - Tool calls happen at the right moments
  - Agent responses are concise and in-character
  - Timers fire (pre-alert + expiry)
  - Demo speed mode works
  - Barge-in works
  - State updates flow correctly
"""

import asyncio
import json
import os
import ssl
import time
from pathlib import Path

import websockets

DEPLOYED_URL = os.environ.get(
    "DEPLOYED_URL",
    "https://souschef-live-5z4a6smnda-uc.a.run.app",
)

REPORT_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts" / "demo-rehearsal"


def ws_url(session_id: str) -> str:
    base = DEPLOYED_URL.replace("https://", "wss://").replace("http://", "ws://")
    return f"{base}/ws?session_id={session_id}"


def setup_msg() -> str:
    return json.dumps({
        "setup": {
            "generation_config": {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {"voice_name": "Aoede"},
                    },
                },
            },
            "input_audio_transcription": {},
            "output_audio_transcription": {},
        }
    })


def text_msg(text: str) -> str:
    return json.dumps({"type": "text", "text": text})


def control_msg(action: str, value=True) -> str:
    return json.dumps({"type": "control", "action": action, "value": value})


async def collect_until(ws, timeout_s: float, stop_on_turn_complete=True):
    events = []
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
        except asyncio.TimeoutError:
            continue
        except websockets.exceptions.ConnectionClosed:
            break

        if isinstance(msg, bytes):
            events.append({"_type": "audio_chunk", "size": len(msg), "ts": time.time()})
            continue

        try:
            data = json.loads(msg)
            data["_ts"] = time.time()
            events.append(data)
            if stop_on_turn_complete and data.get("serverContent", {}).get("turnComplete"):
                break
        except json.JSONDecodeError:
            events.append({"_type": "raw", "data": msg[:200], "ts": time.time()})

    return events


def extract_transcription(events):
    parts = []
    for e in events:
        sc = e.get("serverContent", {})
        ot = sc.get("outputTranscription", {})
        if ot and ot.get("text"):
            parts.append(ot["text"])
    return "".join(parts).strip()


def extract_tool_calls(events):
    return [e for e in events if e.get("type") == "tool_call"]


def extract_state_updates(events):
    return [e for e in events if e.get("type") == "state_update"]


def summarize_step(step_name, sent_text, events, t_start):
    duration = time.time() - t_start
    transcript = extract_transcription(events)
    tools = extract_tool_calls(events)
    states = extract_state_updates(events)
    audio_count = sum(1 for e in events if e.get("_type") == "audio_chunk")
    audio_bytes = sum(e.get("size", 0) for e in events if e.get("_type") == "audio_chunk")

    summary = {
        "step": step_name,
        "sent": sent_text,
        "duration_s": round(duration, 2),
        "agent_response": transcript,
        "agent_word_count": len(transcript.split()) if transcript else 0,
        "tool_calls": [{"name": t["name"], "args": t.get("args", {}), "result": t.get("result", {})} for t in tools],
        "state_updates_count": len(states),
        "last_state": states[-1] if states else None,
        "audio_chunks": audio_count,
        "audio_bytes": audio_bytes,
    }
    return summary


async def run_demo_flow():
    """Simulate the full demo conversation and capture everything."""
    session_id = f"demo_rehearsal_{int(time.time())}"
    ssl_ctx = ssl.create_default_context()
    results = []

    print(f"\n{'='*70}")
    print(f"DEMO REHEARSAL — Session: {session_id}")
    print(f"Target: {DEPLOYED_URL}")
    print(f"{'='*70}\n")

    async with websockets.connect(
        ws_url(session_id),
        ssl=ssl_ctx,
        open_timeout=15,
        close_timeout=10,
        max_size=2**22,
    ) as ws:
        # --- Setup ---
        await ws.send(setup_msg())
        await asyncio.sleep(2)
        print("[OK] WebSocket connected and setup sent\n")

        # --- Step 1: Enable Demo Speed ---
        print("--- STEP 1: Enable Demo 10x Speed ---")
        t = time.time()
        await ws.send(control_msg("demo_speed", True))
        await asyncio.sleep(1)
        print("[OK] Demo speed enabled\n")

        # --- Step 2: Recipe Generation (Demo 0:15-0:30) ---
        print("--- STEP 2: Recipe Generation (ingredients → recipe) ---")
        t = time.time()
        msg = "Chef, I have chicken thighs, garlic, and butter. What should we cook?"
        await ws.send(text_msg(msg))
        events = await collect_until(ws, timeout_s=30)
        summary = summarize_step("recipe_generation", msg, events, t)
        results.append(summary)
        print(f"  Agent: {summary['agent_response'][:200]}")
        print(f"  Words: {summary['agent_word_count']}")
        print(f"  Tools: {[t['name'] for t in summary['tool_calls']]}")
        print(f"  Duration: {summary['duration_s']}s")
        print(f"  Audio: {summary['audio_chunks']} chunks ({summary['audio_bytes']} bytes)")
        print()

        # --- Step 3: Confirm recipe, ask to start ---
        print("--- STEP 3: Confirm recipe and start prep ---")
        t = time.time()
        msg = "Let's do garlic butter chicken thighs. What's first?"
        await ws.send(text_msg(msg))
        events = await collect_until(ws, timeout_s=30)
        summary = summarize_step("confirm_recipe_start_prep", msg, events, t)
        results.append(summary)
        print(f"  Agent: {summary['agent_response'][:200]}")
        print(f"  Tools: {[t['name'] for t in summary['tool_calls']]}")
        print(f"  Duration: {summary['duration_s']}s")
        print()

        # --- Step 4: Simulate bad knife grip concern (Demo 0:30-1:10) ---
        print("--- STEP 4: Technique question (simulating knife grip moment) ---")
        t = time.time()
        msg = "I'm mincing the garlic now. Is my technique okay if I use flat fingers instead of curled?"
        await ws.send(text_msg(msg))
        events = await collect_until(ws, timeout_s=30)
        summary = summarize_step("knife_technique", msg, events, t)
        results.append(summary)
        print(f"  Agent: {summary['agent_response'][:200]}")
        print(f"  Tools: {[t['name'] for t in summary['tool_calls']]}")
        print(f"  Duration: {summary['duration_s']}s")
        print()

        # --- Step 5: Barge-in test ---
        print("--- STEP 5: Barge-in test (send while agent may still be speaking) ---")
        t = time.time()
        msg = "Like this?"
        await ws.send(text_msg(msg))
        events = await collect_until(ws, timeout_s=15)
        summary = summarize_step("barge_in", msg, events, t)
        results.append(summary)
        print(f"  Agent: {summary['agent_response'][:200]}")
        print(f"  Duration: {summary['duration_s']}s")
        print()

        # --- Step 6: Pan readiness + ask for timer (Demo 1:10-2:00) ---
        print("--- STEP 6: Pan readiness → sear → timer ---")
        t = time.time()
        msg = "Okay, the pan is hot and oil is shimmering. I'm placing the chicken now, skin side down. Please set a 2-minute sear timer and update the step to sear_side_1."
        await ws.send(text_msg(msg))
        events = await collect_until(ws, timeout_s=30)
        summary = summarize_step("sear_timer", msg, events, t)
        results.append(summary)
        print(f"  Agent: {summary['agent_response'][:200]}")
        print(f"  Tools: {[t['name'] for t in summary['tool_calls']]}")
        if summary['last_state']:
            print(f"  State: step={summary['last_state'].get('current_step')}, recipe={summary['last_state'].get('recipe_name')}")
            timers = summary['last_state'].get('timers', [])
            if isinstance(timers, dict):
                timers = list(timers.values())
            print(f"  Timers: {len(timers)} active")
            for tinfo in timers:
                tid = tinfo.get('id', '?')
                print(f"    {tid}: {tinfo.get('label')} — {tinfo.get('effective_seconds')}s effective (demo speed)")
        print(f"  Duration: {summary['duration_s']}s")
        print()

        # --- Step 7: Wait for timer events (pre-alert + expiry) ---
        print("--- STEP 7: Waiting for timer pre-alert and expiry events ---")
        t = time.time()
        events = await collect_until(ws, timeout_s=45, stop_on_turn_complete=False)
        timer_events = [e for e in events if e.get("type") == "state_update"]
        transcripts = extract_transcription(events)
        audio_count = sum(1 for e in events if e.get("_type") == "audio_chunk")
        summary = {
            "step": "timer_wait",
            "sent": "(waiting for timer events)",
            "duration_s": round(time.time() - t, 2),
            "agent_response": transcripts,
            "agent_word_count": len(transcripts.split()) if transcripts else 0,
            "tool_calls": [],
            "state_updates_count": len(timer_events),
            "last_state": timer_events[-1] if timer_events else None,
            "audio_chunks": audio_count,
            "audio_bytes": sum(e.get("size", 0) for e in events if e.get("_type") == "audio_chunk"),
        }
        results.append(summary)
        print(f"  State updates received: {len(timer_events)}")
        print(f"  Agent speech during wait: {transcripts[:200] if transcripts else '(none)'}")
        print(f"  Audio chunks during wait: {audio_count}")
        print(f"  Duration: {summary['duration_s']}s")
        print()

        # --- Step 8: Barge-in during/after timer (Demo 2:00-3:00) ---
        print("--- STEP 8: Barge-in — 'Why not move it?' ---")
        t = time.time()
        msg = "Wait, why shouldn't I move the chicken while searing?"
        await ws.send(text_msg(msg))
        events = await collect_until(ws, timeout_s=20)
        summary = summarize_step("barge_in_timer", msg, events, t)
        results.append(summary)
        print(f"  Agent: {summary['agent_response'][:200]}")
        print(f"  Duration: {summary['duration_s']}s")
        print()

        # --- Step 9: Flip + second sear (Demo 3:00-3:50) ---
        print("--- STEP 9: Flip and second sear ---")
        t = time.time()
        msg = "Okay I've flipped the chicken. It looks golden brown on top. Should I set another timer for the second side? Please update step to sear_side_2 and set a 2-minute timer."
        await ws.send(text_msg(msg))
        events = await collect_until(ws, timeout_s=30)
        summary = summarize_step("flip_second_sear", msg, events, t)
        results.append(summary)
        print(f"  Agent: {summary['agent_response'][:200]}")
        print(f"  Tools: {[t['name'] for t in summary['tool_calls']]}")
        print(f"  Duration: {summary['duration_s']}s")
        print()

        # --- Step 10: Rest phase ---
        print("--- STEP 10: Rest phase ---")
        t = time.time()
        msg = "Both sides are done and golden. The chicken looks great. Should I rest it now? Please set a 3-minute rest timer and update step to rest."
        await ws.send(text_msg(msg))
        events = await collect_until(ws, timeout_s=30)
        summary = summarize_step("rest_phase", msg, events, t)
        results.append(summary)
        print(f"  Agent: {summary['agent_response'][:200]}")
        print(f"  Tools: {[t['name'] for t in summary['tool_calls']]}")
        print(f"  Duration: {summary['duration_s']}s")
        print()

        # --- Step 11: End session ---
        print("--- STEP 11: End session ---")
        await ws.send(control_msg("end_session", True))
        await asyncio.sleep(2)
        print("[OK] Session ended\n")

    # --- Write full report ---
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"report_{session_id}.json"
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Full report saved to: {report_path}\n")

    # --- Print analysis ---
    print(f"\n{'='*70}")
    print("DEMO REHEARSAL ANALYSIS")
    print(f"{'='*70}\n")

    all_tools_called = set()
    total_words = 0
    issues = []

    for r in results:
        for tc in r["tool_calls"]:
            all_tools_called.add(tc["name"])
        total_words += r["agent_word_count"]

        if r["agent_word_count"] > 50 and r["step"] != "timer_wait":
            issues.append(f"  [VERBOSE] Step '{r['step']}': {r['agent_word_count']} words (target: <30)")

        if r["duration_s"] > 15 and r["step"] not in ("timer_wait",):
            issues.append(f"  [SLOW] Step '{r['step']}': {r['duration_s']}s (target: <10s)")

    print(f"Tools called across session: {sorted(all_tools_called)}")
    expected_tools = {"update_recipe", "set_timer", "update_cooking_step"}
    missing_tools = expected_tools - all_tools_called
    if missing_tools:
        issues.append(f"  [MISSING TOOLS] Expected but never called: {missing_tools}")
    else:
        print(f"  All expected tools called!")

    print(f"\nTotal agent words: {total_words}")
    print(f"Average words per turn: {total_words / max(1, len([r for r in results if r['step'] != 'timer_wait'])):.0f}")

    timer_step = next((r for r in results if r["step"] == "sear_timer"), None)
    if timer_step:
        timer_tools = [t for t in timer_step["tool_calls"] if t["name"] == "set_timer"]
        if timer_tools:
            eff = timer_tools[0].get("result", {}).get("effective_seconds")
            print(f"\nTimer effective seconds (with demo 10x): {eff}s")
            if eff and eff > 15:
                issues.append(f"  [DEMO SPEED] Timer effective={eff}s, expected ≤12s with 10x")
            elif eff:
                print(f"  Demo speed working correctly!")
        else:
            issues.append(f"  [NO TIMER] set_timer not called in sear step")

    timer_wait = next((r for r in results if r["step"] == "timer_wait"), None)
    if timer_wait:
        if timer_wait["state_updates_count"] > 0:
            print(f"\nTimer events received during wait: {timer_wait['state_updates_count']}")
            if timer_wait["agent_word_count"] > 0:
                print(f"  Agent spoke during timer: \"{timer_wait['agent_response'][:150]}\"")
            else:
                issues.append(f"  [SILENT TIMER] No agent speech during timer wait — pre-alert/expiry may not have triggered speech")
        else:
            issues.append(f"  [NO TIMER EVENTS] No state updates during timer wait")

    if issues:
        print(f"\n--- ISSUES FOUND ({len(issues)}) ---")
        for i in issues:
            print(i)
    else:
        print(f"\n--- NO ISSUES FOUND ---")

    print(f"\n{'='*70}")
    print("END OF DEMO REHEARSAL")
    print(f"{'='*70}\n")

    return results, issues


if __name__ == "__main__":
    asyncio.run(run_demo_flow())
