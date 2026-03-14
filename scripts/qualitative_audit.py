"""Qualitative audit of agent behavior against deployed service.

Runs targeted scenarios through the real deployed backend, captures every
WebSocket event, and prints a detailed human-readable report analyzing:
- Tool call correctness (name, args, sequencing)
- Transcription quality (persona, conciseness, relevance)
- State transitions (recipe, step, timers)
- Proactive vs. reactive behavior
- UX red flags (long silences, garbled output, character breaks)

Usage:
    source .env && GEMINI_API_KEY="$GEMINI_API_KEY" python scripts/qualitative_audit.py
"""

import asyncio
import base64
import json
import os
import ssl
import sys
import time
from pathlib import Path

import websockets

DEPLOYED_URL = os.environ.get(
    "DEPLOYED_URL",
    "https://souschef-live-504591545979.europe-west1.run.app",
)
FIXTURES = Path(__file__).resolve().parent.parent / "harness" / "fixtures" / "images"

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ws_url(sid: str) -> str:
    base = DEPLOYED_URL.replace("https://", "wss://").replace("http://", "ws://")
    return f"{base}/ws?session_id={sid}"


def setup_msg() -> str:
    return json.dumps({
        "setup": {
            "generation_config": {
                "response_modalities": ["AUDIO"],
                "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": "Aoede"}}},
            },
            "input_audio_transcription": {},
            "output_audio_transcription": {},
        }
    })


def img_msg(filename: str) -> str:
    path = FIXTURES / filename
    b64 = base64.b64encode(path.read_bytes()).decode()
    return json.dumps({"type": "image", "data": b64, "mimeType": "image/jpeg"})


def txt_msg(text: str) -> str:
    return json.dumps({"type": "text", "text": text})


async def collect(ws, timeout_s=40):
    events = []
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
        except asyncio.TimeoutError:
            continue
        except websockets.exceptions.ConnectionClosed:
            break
        if isinstance(msg, bytes):
            events.append({"_type": "audio", "bytes": len(msg)})
        else:
            try:
                events.append(json.loads(msg))
            except json.JSONDecodeError:
                events.append({"_type": "raw", "data": msg[:200]})
        if isinstance(events[-1], dict) and events[-1].get("serverContent", {}).get("turnComplete"):
            break
    return events


def extract_transcript(events, direction="output"):
    key = f"{direction}Transcription"
    parts = []
    for e in events:
        sc = e.get("serverContent", {})
        t = sc.get(key, {})
        if t and t.get("text"):
            parts.append(t["text"])
    return " ".join(parts).strip()


def extract_tools(events):
    return [e for e in events if e.get("type") == "tool_call"]


def extract_states(events):
    return [e for e in events if e.get("type") == "state_update"]


def count_audio(events):
    return sum(1 for e in events if isinstance(e, dict) and e.get("_type") == "audio")


def print_section(title):
    print(f"\n{'='*70}")
    print(f"{BOLD}{CYAN}{title}{RESET}")
    print(f"{'='*70}")


def analyze_transcript(transcript, context, checks):
    issues = []
    if not transcript:
        issues.append(f"{RED}NO TRANSCRIPTION received{RESET}")
        return issues

    word_count = len(transcript.split())
    if word_count > 60:
        issues.append(f"{YELLOW}VERBOSE: {word_count} words (target: <30){RESET}")

    forbidden = ["as an ai", "i'm an ai", "language model", "i cannot", "i can't help"]
    for f in forbidden:
        if f in transcript.lower():
            issues.append(f"{RED}CHARACTER BREAK: '{f}' found{RESET}")

    for check_name, keywords in checks.items():
        found = [k for k in keywords if k.lower() in transcript.lower()]
        if not found:
            issues.append(f"{YELLOW}MISSING expected content '{check_name}': none of {keywords} found{RESET}")

    return issues


async def run_scenario(name, sid, steps):
    print_section(f"SCENARIO: {name}")
    all_issues = []
    ssl_ctx = ssl.create_default_context()

    try:
        async with websockets.connect(
            ws_url(sid), ssl=ssl_ctx, open_timeout=15, close_timeout=10,
        ) as ws:
            await ws.send(setup_msg())

            for i, step in enumerate(steps):
                turn_label = step.get("label", f"Turn {i+1}")
                print(f"\n{BOLD}--- {turn_label} ---{RESET}")

                if step.get("image"):
                    print(f"  Sending image: {step['image']}")
                    await ws.send(img_msg(step["image"]))

                if step.get("text"):
                    print(f"  Sending text: \"{step['text']}\"")
                    await ws.send(txt_msg(step["text"]))

                events = await collect(ws, timeout_s=step.get("timeout", 40))

                # Audio
                audio_count = count_audio(events)
                print(f"  Audio chunks: {audio_count}")

                # Transcription
                out_transcript = extract_transcript(events, "output")
                in_transcript = extract_transcript(events, "input")
                if in_transcript:
                    print(f"  {CYAN}Input transcription:{RESET} \"{in_transcript}\"")
                if out_transcript:
                    print(f"  {GREEN}Agent said:{RESET} \"{out_transcript}\"")
                else:
                    print(f"  {YELLOW}Agent said:{RESET} (no transcription, {audio_count} audio chunks)")

                # Tool calls
                tools = extract_tools(events)
                for tc in tools:
                    name_str = tc.get("name", "?")
                    args = tc.get("args", {})
                    result = tc.get("result", {})
                    print(f"  {BOLD}Tool call:{RESET} {name_str}({json.dumps(args)})")
                    print(f"    Result: {json.dumps(result, default=str)[:200]}")

                # State updates
                states = extract_states(events)
                for su in states:
                    recipe = su.get("recipe_name", "")
                    step_name = su.get("current_step", "")
                    timers = su.get("timers", [])
                    print(f"  {BOLD}State:{RESET} recipe={recipe}, step={step_name}, timers={len(timers)}")

                # Quality checks
                checks = step.get("expect_keywords", {})
                issues = analyze_transcript(out_transcript, turn_label, checks)
                for issue in issues:
                    print(f"  {issue}")
                all_issues.extend([(turn_label, iss) for iss in issues])

                # Tool expectation checks
                expected_tools = step.get("expect_tools", [])
                actual_tool_names = [tc.get("name") for tc in tools]
                for et in expected_tools:
                    if et not in actual_tool_names:
                        msg = f"{YELLOW}EXPECTED tool '{et}' not called (got: {actual_tool_names}){RESET}"
                        print(f"  {msg}")
                        all_issues.append((turn_label, msg))

    except Exception as e:
        print(f"\n{RED}CONNECTION ERROR: {e}{RESET}")
        all_issues.append(("connection", str(e)))

    return all_issues


async def main():
    print(f"{BOLD}SousChef Live — Qualitative Audit{RESET}")
    print(f"Target: {DEPLOYED_URL}")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    all_issues = []

    # ---- Scenario 1: Recipe initiation from ingredients ----
    issues = await run_scenario(
        "Recipe Initiation from Ingredients",
        f"audit_recipe_{int(time.time())}",
        [
            {
                "label": "Show ingredients + ask to cook",
                "image": "garlic_butter_ingredients.jpg",
                "text": "Chef, I want to cook chicken thighs with what I have here.",
                "expect_keywords": {
                    "food_recognition": ["chicken", "garlic", "butter", "thigh"],
                },
                "expect_tools": ["update_recipe"],
            },
        ],
    )
    all_issues.extend(issues)

    await asyncio.sleep(2)

    # ---- Scenario 2: Proactive safety intervention ----
    issues = await run_scenario(
        "Proactive Safety Intervention (Knife Grip)",
        f"audit_safety_{int(time.time())}",
        [
            {
                "label": "Context: cooking garlic butter chicken",
                "text": "I'm making garlic butter chicken thighs. Starting to mince the garlic.",
                "expect_keywords": {},
            },
            {
                "label": "Show poor knife grip",
                "image": "poor_knife_grip.jpg",
                "text": "Mincing the garlic now.",
                "expect_keywords": {},
            },
        ],
    )
    all_issues.extend(issues)

    await asyncio.sleep(2)

    # ---- Scenario 3: Cold pan detection ----
    issues = await run_scenario(
        "Cold Pan Detection + Heat Guidance",
        f"audit_pan_{int(time.time())}",
        [
            {
                "label": "Context: ready to sear",
                "text": "I have the chicken thighs seasoned and ready. Pan has oil.",
                "expect_keywords": {},
            },
            {
                "label": "Show cold pan + ask to cook",
                "image": "cold_pan_oil.jpg",
                "text": "I'm about to put the chicken in the pan. Ready?",
                "expect_keywords": {
                    "heat_guidance": ["wait", "heat", "hot", "shimmer", "ready", "warm", "temperature", "moment", "pan"],
                },
            },
        ],
    )
    all_issues.extend(issues)

    await asyncio.sleep(2)

    # ---- Scenario 4: Timer + state management ----
    issues = await run_scenario(
        "Timer Creation + Step Tracking",
        f"audit_timer_{int(time.time())}",
        [
            {
                "label": "Start searing",
                "image": "chicken_searing.jpg",
                "text": "The chicken just went into the hot pan. Nice sizzle! Start a sear timer please.",
                "expect_tools": ["set_timer"],
                "expect_keywords": {
                    "timer_announcement": ["timer", "minute", "sear", "time"],
                },
            },
        ],
    )
    all_issues.extend(issues)

    await asyncio.sleep(2)

    # ---- Scenario 5: Persona check ----
    issues = await run_scenario(
        "Persona Consistency & Off-Topic Handling",
        f"audit_persona_{int(time.time())}",
        [
            {
                "label": "Identity question",
                "text": "Who are you?",
                "expect_keywords": {
                    "persona": ["chef", "sous", "cook", "kitchen", "guide", "help", "mentor"],
                },
            },
            {
                "label": "Off-topic question",
                "text": "What's the weather in Paris today?",
                "expect_keywords": {
                    "redirect": ["cook", "kitchen", "food", "recipe", "focus", "help", "back"],
                },
            },
        ],
    )
    all_issues.extend(issues)

    await asyncio.sleep(2)

    # ---- Scenario 6: Conciseness check ----
    issues = await run_scenario(
        "Conciseness & Response Length",
        f"audit_concise_{int(time.time())}",
        [
            {
                "label": "Open-ended cooking question",
                "text": "Tell me everything about cooking the perfect steak.",
                "expect_keywords": {},
            },
        ],
    )
    all_issues.extend(issues)

    await asyncio.sleep(2)

    # ---- Scenario 7: Burnt food detection ----
    issues = await run_scenario(
        "Burnt Food Detection",
        f"audit_burnt_{int(time.time())}",
        [
            {
                "label": "Show burnt food + ask",
                "image": "burnt_food.jpg",
                "text": "Does this look okay or is it overdone?",
                "expect_keywords": {},
            },
        ],
    )
    all_issues.extend(issues)

    await asyncio.sleep(2)

    # ---- Scenario 8: Golden sear assessment ----
    issues = await run_scenario(
        "Golden Sear Positive Assessment",
        f"audit_golden_{int(time.time())}",
        [
            {
                "label": "Context: searing chicken",
                "text": "I'm searing chicken thighs. Just flipped them.",
                "expect_keywords": {},
            },
            {
                "label": "Show golden sear",
                "image": "golden_brown_sear.jpg",
                "text": "How does this side look?",
                "expect_keywords": {},
            },
        ],
    )
    all_issues.extend(issues)

    # ---- Summary ----
    print_section("AUDIT SUMMARY")
    if not all_issues:
        print(f"{GREEN}ALL CHECKS PASSED — No issues detected{RESET}")
    else:
        warnings = [i for i in all_issues if "YELLOW" in str(i[1]) or "MISSING" in str(i[1])]
        errors = [i for i in all_issues if "RED" in str(i[1]) or "CHARACTER BREAK" in str(i[1]) or "NO TRANSCRIPTION" in str(i[1])]
        print(f"Total issues: {len(all_issues)}")
        print(f"  {RED}Errors: {len(errors)}{RESET}")
        print(f"  {YELLOW}Warnings: {len(warnings)}{RESET}")
        for turn, issue in all_issues:
            print(f"  [{turn}] {issue}")

    return len([i for i in all_issues if "RED" in str(i[1])])


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(min(exit_code, 1))
