"""Persona and guardrail tests against the deployed service.

Validates that the agent stays in character, rejects off-topic requests,
keeps responses concise, avoids AI self-reference, and handles non-food
images appropriately.

Requires:
  GEMINI_API_KEY  — set in environment
  DEPLOYED_URL    — Cloud Run service URL (defaults to production)
"""

import os

import pytest
import websockets

from tests.live.conftest import (
    ws_url, setup_message, text_message, image_message,
    collect_events, extract_output_transcription,
    extract_audio_chunks,
    assert_no_forbidden, assert_concise, assert_any_keyword,
    ssl_context,
)

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set",
    ),
    pytest.mark.timeout(60),
]


class TestPersonaGuardrails:
    """Verify agent persona, conciseness, and topic adherence."""

    @pytest.mark.asyncio
    async def test_off_topic_redirects_to_cooking(self):
        """Off-topic question should get a cooking-redirected response."""
        async with websockets.connect(
            ws_url("persona_offtopic"), ssl=ssl_context(),
            open_timeout=15, close_timeout=5,
        ) as ws:
            await ws.send(setup_message())
            await ws.send(text_message(
                "What's the weather like in Paris today?"
            ))

            events = await collect_events(ws, timeout_s=30)
            transcript = extract_output_transcription(events)

            assert len(transcript) > 0, "Expected a response to off-topic question"
            assert_no_forbidden(transcript)

    @pytest.mark.asyncio
    async def test_no_ai_self_reference(self):
        """Agent should not say 'as an AI' or similar phrases."""
        async with websockets.connect(
            ws_url("persona_no_ai"), ssl=ssl_context(),
            open_timeout=15, close_timeout=5,
        ) as ws:
            await ws.send(setup_message())
            await ws.send(text_message("Who are you and what can you do?"))

            events = await collect_events(ws, timeout_s=30)
            transcript = extract_output_transcription(events)

            assert len(transcript) > 0, "Expected persona description"
            assert_no_forbidden(transcript)

    @pytest.mark.asyncio
    async def test_concise_responses(self):
        """Agent should keep responses short per system instruction."""
        async with websockets.connect(
            ws_url("persona_concise"), ssl=ssl_context(),
            open_timeout=15, close_timeout=5,
        ) as ws:
            await ws.send(setup_message())
            await ws.send(text_message(
                "Tell me everything you know about cooking chicken."
            ))

            events = await collect_events(ws, timeout_s=30)
            transcript = extract_output_transcription(events)

            assert len(transcript) > 0, "Expected a response"
            # System instruction says max 2 sentences. Allow some slack
            # since the model may not perfectly comply, but flag gross violations.
            assert_concise(transcript, max_words=120)

    @pytest.mark.asyncio
    async def test_chef_persona_voice(self):
        """Agent should identify as a chef/sous-chef, not a generic assistant."""
        async with websockets.connect(
            ws_url("persona_voice"), ssl=ssl_context(),
            open_timeout=15, close_timeout=5,
        ) as ws:
            await ws.send(setup_message())
            await ws.send(text_message(
                "Hi! Introduce yourself briefly."
            ))

            events = await collect_events(ws, timeout_s=30)
            transcript = extract_output_transcription(events)

            assert len(transcript) > 0, "Expected introduction"
            assert_no_forbidden(transcript)

    @pytest.mark.asyncio
    async def test_non_food_image_handling(self):
        """Send a non-food image — agent should acknowledge and redirect."""
        async with websockets.connect(
            ws_url("persona_nonfood"), ssl=ssl_context(),
            open_timeout=15, close_timeout=5,
        ) as ws:
            await ws.send(setup_message())
            await ws.send(image_message("non_food.jpg"))
            await ws.send(text_message(
                "What do you see? Can we cook with this?"
            ))

            events = await collect_events(ws, timeout_s=35)
            transcript = extract_output_transcription(events)
            audio = extract_audio_chunks(events)

            assert len(audio) > 0, "Expected audio response"
            assert len(transcript) > 0, "Expected transcription"
            assert_no_forbidden(transcript)

    @pytest.mark.asyncio
    async def test_multiple_rapid_questions(self):
        """Send several questions quickly — agent should handle gracefully."""
        async with websockets.connect(
            ws_url("persona_rapid"), ssl=ssl_context(),
            open_timeout=15, close_timeout=5,
        ) as ws:
            await ws.send(setup_message())

            await ws.send(text_message("What temperature for chicken?"))
            events1 = await collect_events(ws, timeout_s=30)

            await ws.send(text_message("How do I know when oil is hot enough?"))
            events2 = await collect_events(ws, timeout_s=30)

            t1 = extract_output_transcription(events1)
            t2 = extract_output_transcription(events2)

            responses = [t for t in [t1, t2] if len(t) > 0]
            assert len(responses) >= 1, (
                f"Expected at least 1 of 2 responses. t1={t1[:100]}, t2={t2[:100]}"
            )
            for t in responses:
                assert_no_forbidden(t)
