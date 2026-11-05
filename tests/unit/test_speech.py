"""Consultation speech-to-text: decoding, which transcriber runs, and the audio-egress opt-in."""

import wave
from io import BytesIO
from types import SimpleNamespace

import numpy as np
import pytest

from services.platform.config import Settings
from services.platform.tracing import capture_model_calls
from services.scribe import speech


def wav(samples: np.ndarray, rate: int, channels: int = 1) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes((samples * 32767).astype("<i2").tobytes())
    return buffer.getvalue()


def test_stereo_48k_becomes_mono_16k_with_levels_kept():
    left = np.full(48_000, 0.5, dtype=np.float32)
    right = np.full(48_000, -0.5, dtype=np.float32)
    stereo = np.column_stack([left, right]).reshape(-1)
    out = speech.wav_to_samples(wav(stereo, 48_000, channels=2))
    assert out.dtype == np.float32 and len(out) == 16_000
    assert abs(float(out.mean())) < 1e-3  # +0.5 and -0.5 average out to silence
    mono = speech.wav_to_samples(wav(np.full(16_000, 0.25, dtype=np.float32), 16_000))
    assert np.allclose(mono, 0.25, atol=1e-3)


def test_local_is_the_default_and_gemini_needs_an_explicit_audio_egress_opt_in():
    assert isinstance(
        speech.build_speech_transcriber(Settings(_env_file=None)), speech.LocalSpeechTranscriber
    )
    with pytest.raises(ValueError, match="ALLOW_AUDIO_EGRESS"):
        Settings(_env_file=None, speech_provider="gemini", chat_provider="gemini", chat_api_key="k")
    chosen = speech.build_speech_transcriber(
        Settings(
            _env_file=None,
            speech_provider="gemini",
            allow_audio_egress=True,
            chat_provider="gemini",
            chat_api_key="k",
            chat_model="gemini-large",
            chat_small_model="gemini-small",
        )
    )
    assert isinstance(chosen, speech.GeminiSpeechTranscriber) and chosen.model == "gemini-small"


def _fake_genai(monkeypatch, *, text: str | None = None, error: Exception | None = None) -> dict:
    seen: dict = {}

    class Models:
        async def generate_content(self, *, model, contents, config):
            seen.update(model=model, contents=contents, temperature=config.temperature)
            if error:
                raise error
            usage = SimpleNamespace(
                prompt_token_count=540, candidates_token_count=60, thoughts_token_count=20
            )
            return SimpleNamespace(text=text, usage_metadata=usage)

    class Client:
        def __init__(self, api_key):
            seen["api_key"] = api_key
            self.aio = SimpleNamespace(models=Models())

    from google import genai

    monkeypatch.setattr(genai, "Client", Client)
    return seen


async def test_gemini_transcribes_verbatim_and_is_metered(monkeypatch):
    seen = _fake_genai(monkeypatch, text=" Mujhe teen din se bukhar hai. ")
    audio = wav(np.zeros(16_000, dtype=np.float32), 16_000)
    with capture_model_calls() as spans:
        text = await speech.GeminiSpeechTranscriber(api_key="k", model="g").transcribe(audio)
    assert text == "Mujhe teen din se bukhar hai."
    assert seen["temperature"] == 0 and "Do not translate" in seen["contents"][1]
    [span] = spans
    assert (span.tokens_in, span.tokens_out, span.tokens_estimated) == (540, 80, False)


async def test_gemini_failure_is_unavailable_and_recorded(monkeypatch):
    _fake_genai(monkeypatch, error=TimeoutError())
    audio = wav(np.zeros(16_000, dtype=np.float32), 16_000)
    with capture_model_calls() as spans, pytest.raises(speech.SpeechUnavailable):
        await speech.GeminiSpeechTranscriber(api_key="k", model="g").transcribe(audio)
    assert spans[0].status == "error"


async def test_invalid_audio_never_reaches_the_provider(monkeypatch):
    seen = _fake_genai(monkeypatch, text="x")
    with pytest.raises(ValueError):
        await speech.GeminiSpeechTranscriber(api_key="k", model="g").transcribe(b"not audio")
    assert "contents" not in seen


async def test_the_page_is_told_truthfully_where_audio_goes(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from services.api.routers.scribe import router

    app = FastAPI()
    app.include_router(router)
    headers = {"X-Dev-User-Id": "d", "X-Dev-Role": "doctor"}
    async with AsyncClient(transport=ASGITransport(app), base_url="http://t") as client:
        assert (await client.get("/api/scribe/speech", headers=headers)).json() == {
            "provider": "local",
            "audio_leaves_boundary": False,
        }
        monkeypatch.setenv("MEDPAL_SPEECH_PROVIDER", "gemini")
        monkeypatch.setenv("MEDPAL_ALLOW_AUDIO_EGRESS", "true")
        from services.platform.config import get_settings

        get_settings.cache_clear()
        try:
            assert (await client.get("/api/scribe/speech", headers=headers)).json()["audio_leaves_boundary"]
        finally:
            monkeypatch.delenv("MEDPAL_SPEECH_PROVIDER")
            monkeypatch.delenv("MEDPAL_ALLOW_AUDIO_EGRESS")
            get_settings.cache_clear()
        headers.update({"X-Dev-Role": "patient", "X-Dev-Patient-Id": "p"})
        assert (await client.get("/api/scribe/speech", headers=headers)).status_code == 403


def test_the_medicine_vocabulary_reaches_both_transcribers():
    settings = Settings(_env_file=None, speech_vocabulary="paracetamol, cetirizine")
    local = speech.build_speech_transcriber(settings)
    assert isinstance(local, speech.LocalSpeechTranscriber)
    assert local.prompt and "paracetamol, cetirizine" in local.prompt
    hosted = speech.GeminiSpeechTranscriber(api_key="k", model="g", vocabulary="paracetamol")
    assert "paracetamol" in hosted.prompt and "never add them" in hosted.prompt
