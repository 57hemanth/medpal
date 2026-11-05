"""Offline speech-to-text. Audio is processed in memory and is never persisted."""

import asyncio
import wave
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

MAX_AUDIO_BYTES = 16 * 1024 * 1024
MAX_AUDIO_SECONDS = 1800


class SpeechUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _model(path: str) -> Any:
    if not Path(path).is_dir():
        raise SpeechUnavailable("local speech model directory is unavailable")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SpeechUnavailable("install the speech extra to enable transcription") from exc
    return WhisperModel(path, device="cpu", compute_type="int8", local_files_only=True)


SAMPLE_RATE = 16_000


def wav_to_samples(content: bytes) -> Any:
    """PCM WAV -> mono float32 at 16 kHz, what Whisper expects. Decoding here (not in the model library)
    keeps one small, tested path and no native media decoder in the request path."""
    import numpy as np

    with wave.open(BytesIO(content)) as audio:
        rate, channels, width = audio.getframerate(), audio.getnchannels(), audio.getsampwidth()
        raw = audio.readframes(audio.getnframes())
    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        ints = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        data = np.where(ints >= 1 << 23, ints - (1 << 24), ints).astype(np.float32) / float(1 << 23)
    else:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / float(1 << 31)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE and len(data):
        positions = np.linspace(0, len(data) - 1, int(len(data) * SAMPLE_RATE / rate))
        data = np.interp(positions, np.arange(len(data)), data).astype(np.float32)
    return data


def validate_audio(content: bytes) -> None:
    if len(content) > MAX_AUDIO_BYTES:
        raise ValueError("audio_too_large")
    try:
        with wave.open(BytesIO(content)) as audio:
            duration = audio.getnframes() / audio.getframerate()
            if not 0 < duration <= MAX_AUDIO_SECONDS:
                raise ValueError("audio_duration_out_of_range")
            if audio.getnchannels() not in (1, 2) or audio.getsampwidth() not in (1, 2, 3, 4):
                raise ValueError("unsupported_audio_format")
            if (
                len(audio.readframes(audio.getnframes()))
                != audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
            ):
                raise ValueError("truncated_audio")
    except (wave.Error, EOFError, ZeroDivisionError) as exc:
        raise ValueError("upload_pcm_wav_audio") from exc


class LocalSpeechTranscriber:
    def __init__(self, model_path: str | None, language: str | None = "en", vocabulary: str = "") -> None:
        self.model_path = model_path
        self.prompt = f"Outpatient consultation in India. Medicines: {vocabulary}." if vocabulary else None
        # "en" writes code-mixed Hinglish in Latin script, which the note drafting expects; None = detect.
        self.language = language
        self._lock = asyncio.Lock()

    async def transcribe(self, content: bytes) -> str:
        validate_audio(content)
        if not self.model_path:
            raise SpeechUnavailable("local speech model is not configured")

        def run() -> str:
            segments, _ = _model(self.model_path).transcribe(
                wav_to_samples(content),
                beam_size=5,
                language=self.language,
                vad_filter=True,
                initial_prompt=self.prompt,
            )
            return " ".join(segment.text.strip() for segment in segments).strip()

        # One decoder per process bounds CPU/memory use and avoids concurrent model loading.
        async with self._lock:
            try:
                text = await asyncio.to_thread(run)
            except (OSError, RuntimeError) as exc:
                raise SpeechUnavailable("local transcription is unavailable") from exc
        if not text:
            raise ValueError("no_speech_detected")
        return text


TRANSCRIBE_PROMPT = (
    "Transcribe this doctor-patient consultation audio verbatim.\n"
    "- Write exactly what is said. Do not translate, summarise, correct or add anything.\n"
    "- Hindi or Hinglish speech: write it in Latin script as spoken (e.g. 'teen din se bukhar hai').\n"
    "- Write numbers, doses and measurements as digits with units (e.g. 500 mg, 38.1).\n"
    "- If nothing intelligible is said, return an empty response.\n"
    "Return only the transcript text."
)


class GeminiSpeechTranscriber:
    """Hosted transcription. The AUDIO itself leaves the boundary: speech can't be de-identified the way
    text is (names, numbers and the voice are in it). Enabled only with an explicit opt-in setting; see
    ADR-0016. Metered like every other model call."""

    def __init__(
        self, *, api_key: str, model: str, timeout_seconds: float = 60.0, vocabulary: str = ""
    ) -> None:
        self.model = model
        self.prompt = TRANSCRIBE_PROMPT + (
            f"\n- Spell these as written if you hear them (never add them otherwise): {vocabulary}."
            if vocabulary
            else ""
        )
        self._api_key = api_key
        self._timeout = timeout_seconds

    async def transcribe(self, content: bytes) -> str:
        import time

        from google import genai
        from google.genai import types

        from services.platform.tracing import estimate_tokens, record_model_call

        validate_audio(content)
        client = genai.Client(api_key=self._api_key)
        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=self.model,
                    contents=[types.Part.from_bytes(data=content, mime_type="audio/wav"), self.prompt],
                    config=types.GenerateContentConfig(temperature=0),
                ),
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001  any provider failure is "unavailable" to the doctor
            record_model_call(
                self.model,
                started=started,
                status="error",
                error_type=type(exc).__name__,
                tokens_in=0,
                tokens_out=0,
                estimated=True,
            )
            raise SpeechUnavailable("hosted transcription is unavailable") from exc
        text = (response.text or "").strip()
        usage = response.usage_metadata
        measured = usage is not None and usage.prompt_token_count is not None
        record_model_call(
            self.model,
            started=started,
            tokens_in=(usage.prompt_token_count or 0) if measured and usage else len(content) // 1000,
            tokens_out=(
                ((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0))
                if measured and usage
                else estimate_tokens(text)
            ),
            estimated=not measured,
        )
        if not text:
            raise ValueError("no_speech_detected")
        return text


def build_speech_transcriber(settings: Any) -> "LocalSpeechTranscriber | GeminiSpeechTranscriber":
    if settings.speech_provider == "gemini":
        model = settings.speech_model or settings.chat_small_model or settings.chat_model
        if not settings.chat_api_key:
            raise SpeechUnavailable("MEDPAL_CHAT_API_KEY is required for Gemini transcription")
        return GeminiSpeechTranscriber(
            api_key=settings.chat_api_key,
            model=model,
            timeout_seconds=settings.chat_timeout_seconds * 2,
            vocabulary=settings.speech_vocabulary,
        )
    return LocalSpeechTranscriber(
        settings.speech_model_path, settings.speech_language, settings.speech_vocabulary
    )
