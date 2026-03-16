"""Reproduce transcript bugs: no-spaces + new-message-per-token.

Connects to the deployed service via WebSocket, sends a text message,
and captures EVERY transcription event in raw detail so we can analyze
the exact format Gemini sends (incremental vs accumulated, spacing, etc).
"""

import asyncio
import json
import os
import ssl
import time

import websockets

DEPLOYED_URL = os.environ.get(
    "DEPLOYED_URL",
    "https://souschef-live-5z4a6smnda-uc.a.run.app",
)


def _ws_url(session_id: str = "") -> str:
    base = DEPLOYED_URL.replace("https://", "wss://").replace("http://", "ws://")
    return f"{base}/ws?session_id={session_id}"


def _setup_message() -> str:
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


async def main():
    ssl_ctx = ssl.create_default_context()
    session_id = f"repro_transcript_{int(time.time())}"
    url = _ws_url(session_id)

    print(f"Connecting to {url}...")
    async with websockets.connect(url, ssl=ssl_ctx, open_timeout=15) as ws:
        await ws.send(_setup_message())
        print("Setup sent. Waiting 2s for handshake...")
        await asyncio.sleep(2)

        prompt = "Hello chef! I have chicken thighs and garlic. What should we make?"
        await ws.send(json.dumps({"type": "text", "text": prompt}))
        print(f"Sent text: {prompt!r}\n")

        print("=" * 80)
        print("CAPTURING ALL EVENTS (30s timeout)...")
        print("=" * 80)

        input_transcripts = []
        output_transcripts = []
        other_events = []
        audio_chunk_count = 0

        deadline = time.time() + 30
        turn_complete = False

        while time.time() < deadline and not turn_complete:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            except websockets.exceptions.ConnectionClosed:
                print("[WS CLOSED]")
                break

            if isinstance(msg, bytes):
                audio_chunk_count += 1
                continue

            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                print(f"[RAW] {msg[:200]}")
                continue

            sc = data.get("serverContent", {})

            if sc.get("inputTranscription"):
                t = sc["inputTranscription"]
                text = t.get("text", "")
                finished = t.get("finished")
                entry = {"text": text, "finished": finished, "ts": time.time()}
                input_transcripts.append(entry)
                print(f"[INPUT_TRANSCRIPTION #{len(input_transcripts)}] "
                      f"finished={finished} text={text!r}")

            if sc.get("outputTranscription"):
                t = sc["outputTranscription"]
                text = t.get("text", "")
                finished = t.get("finished")
                entry = {"text": text, "finished": finished, "ts": time.time()}
                output_transcripts.append(entry)
                print(f"[OUTPUT_TRANSCRIPTION #{len(output_transcripts)}] "
                      f"finished={finished} text={text!r}")

            if sc.get("turnComplete"):
                turn_complete = True
                print("[TURN_COMPLETE]")

            if sc.get("interrupted"):
                print("[INTERRUPTED]")

            if data.get("type") == "tool_call":
                print(f"[TOOL_CALL] {data.get('name')} args={data.get('args')}")
                other_events.append(data)

            if data.get("type") == "state_update":
                print(f"[STATE_UPDATE] step={data.get('current_step')}")

            if data.get("type") == "error":
                print(f"[ERROR] {data.get('error')}")

        print("\n" + "=" * 80)
        print("ANALYSIS")
        print("=" * 80)
        print(f"Audio chunks received: {audio_chunk_count}")
        print(f"Input transcription events: {len(input_transcripts)}")
        print(f"Output transcription events: {len(output_transcripts)}")

        if input_transcripts:
            print(f"\n--- INPUT TRANSCRIPTION DETAIL ---")
            for i, t in enumerate(input_transcripts):
                print(f"  #{i+1}: finished={t['finished']}, text={t['text']!r}")
            naive_concat = "".join(t["text"] for t in input_transcripts)
            print(f"  NAIVE CONCAT (current bug): {naive_concat!r}")

        if output_transcripts:
            print(f"\n--- OUTPUT TRANSCRIPTION DETAIL ---")
            for i, t in enumerate(output_transcripts):
                print(f"  #{i+1}: finished={t['finished']}, text={t['text']!r}")
            naive_concat = "".join(t["text"] for t in output_transcripts)
            print(f"  NAIVE CONCAT (current bug): {naive_concat!r}")
            spaced_concat = " ".join(t["text"] for t in output_transcripts)
            print(f"  SPACED CONCAT: {spaced_concat!r}")

        # Simulate OLD (buggy) frontend behavior
        if output_transcripts:
            print(f"\n--- OLD FRONTEND BUG SIMULATION ---")
            transcript_entries = []
            for t in output_transcripts:
                text = t["text"]
                if not text or not text.strip():
                    continue
                last = transcript_entries[-1] if transcript_entries else None
                if last and last["role"] == "chef" and not last["finished"]:
                    last["text"] += text  # BUG: no space!
                else:
                    transcript_entries.append({"role": "chef", "text": text, "finished": False})
            print(f"  Entries created: {len(transcript_entries)}")
            for i, e in enumerate(transcript_entries):
                print(f"  Entry #{i+1}: {e['text']!r}")

        # Simulate NEW (fixed) frontend behavior
        if output_transcripts:
            print(f"\n--- FIXED FRONTEND SIMULATION ---")
            fixed_entries = []
            for t in output_transcripts:
                text = t["text"]
                if not text or not text.strip():
                    continue
                # Find last unfinished entry of same role (scan backwards)
                target = None
                for e in reversed(fixed_entries):
                    if e["role"] == "chef":
                        if not e["finished"]:
                            target = e
                        break
                if target:
                    needs_space = (
                        len(target["text"]) > 0
                        and not target["text"].endswith(" ")
                        and not text.startswith(" ")
                    )
                    target["text"] += (" " if needs_space else "") + text
                else:
                    fixed_entries.append({"role": "chef", "text": text, "finished": False})
            print(f"  Entries created: {len(fixed_entries)}")
            for i, e in enumerate(fixed_entries):
                print(f"  Entry #{i+1}: {e['text']!r}")

        # Simulate interleaving scenario (cook entry between chef entries)
        if output_transcripts and len(output_transcripts) > 3:
            print(f"\n--- INTERLEAVING SIMULATION (cook msg mid-response) ---")
            interleaved_entries_old = []
            interleaved_entries_new = []

            half = len(output_transcripts) // 2
            events = []
            for t in output_transcripts[:half]:
                events.append(("chef", t["text"]))
            events.append(("cook", "Hello chef I have chicken"))
            for t in output_transcripts[half:]:
                events.append(("chef", t["text"]))

            # Old behavior
            for role, text in events:
                if not text or not text.strip():
                    continue
                last = interleaved_entries_old[-1] if interleaved_entries_old else None
                if last and last["role"] == role and not last["finished"]:
                    last["text"] += text
                else:
                    interleaved_entries_old.append({"role": role, "text": text, "finished": False})
            print(f"  OLD: {len(interleaved_entries_old)} entries")
            for i, e in enumerate(interleaved_entries_old):
                print(f"    {e['role']}: {e['text']!r}")

            # New behavior
            for role, text in events:
                if not text or not text.strip():
                    continue
                target = None
                for e in reversed(interleaved_entries_new):
                    if e["role"] == role:
                        if not e["finished"]:
                            target = e
                        break
                if target:
                    needs_space = (
                        len(target["text"]) > 0
                        and not target["text"].endswith(" ")
                        and not text.startswith(" ")
                    )
                    target["text"] += (" " if needs_space else "") + text
                else:
                    interleaved_entries_new.append({"role": role, "text": text, "finished": False})
            print(f"  FIXED: {len(interleaved_entries_new)} entries")
            for i, e in enumerate(interleaved_entries_new):
                print(f"    {e['role']}: {e['text']!r}")


if __name__ == "__main__":
    asyncio.run(main())
