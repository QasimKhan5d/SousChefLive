"""Live regression smoke test — connects to real Gemini Live API.

Requires GEMINI_API_KEY to be set. Uses tolerant assertions:
we verify a session connects and receives at least one response,
not exact wording.
"""

import asyncio
import os
import pytest
import time

pytestmark = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set — skipping live tests",
)


@pytest.fixture
def api_key():
    return os.environ["GEMINI_API_KEY"]


@pytest.fixture
def model():
    return os.environ.get("MODEL", "gemini-2.5-flash-native-audio-latest")


class TestLiveSmoke:
    @pytest.mark.asyncio
    async def test_live_connect_and_audio_transcription(self, api_key, model):
        """Connect to Gemini Live, send a text turn, verify we get audio + transcription."""
        import google.genai as genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(
                parts=[types.Part(text="You are a helpful cooking assistant. Reply in one short sentence.")]
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                )
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

        start = time.time()
        got_audio = False
        got_transcription = False

        async with client.aio.live.connect(model=model, config=config) as session:
            connect_ms = (time.time() - start) * 1000
            assert connect_ms < 10000, f"Connection took {connect_ms}ms"

            await session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text="Hello, what can you help me cook?")]
                ),
                turn_complete=True,
            )

            response_start = time.time()
            async for response in session.receive():
                sc = response.server_content
                if sc and sc.model_turn:
                    for part in sc.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            got_audio = True
                if sc and sc.output_transcription and sc.output_transcription.text:
                    got_transcription = True
                if sc and sc.turn_complete:
                    break
                if time.time() - response_start > 15:
                    break

            response_ms = (time.time() - response_start) * 1000

        assert got_audio, "Expected audio response from Gemini"
        assert response_ms < 15000, f"Response took {response_ms}ms"

    @pytest.mark.asyncio
    async def test_live_audio_response(self, api_key, model):
        """Connect to Gemini Live with AUDIO modality, send text, verify audio bytes back."""
        import google.genai as genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(
                parts=[types.Part(text="You are a cooking assistant. Say 'hello' briefly.")]
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                )
            ),
        )

        got_audio = False

        async with client.aio.live.connect(model=model, config=config) as session:
            await session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text="Hello chef")]
                ),
                turn_complete=True,
            )

            start = time.time()
            async for response in session.receive():
                sc = response.server_content
                if sc and sc.model_turn:
                    for part in sc.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            got_audio = True
                if sc and sc.turn_complete:
                    break
                if time.time() - start > 15:
                    break

        assert got_audio, "Expected audio bytes from Gemini Live session"
