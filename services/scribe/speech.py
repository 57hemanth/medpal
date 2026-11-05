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
    def __init__(self, model_path: str | None) -> None:
        self.model_path = model_path
        self._lock = asyncio.Lock()

    async def transcribe(self, content: bytes) -> str:
        validate_audio(content)
        if not self.model_path:
            raise SpeechUnavailable("local speech model is not configured")

        def run() -> str:
            segments, _ = _model(self.model_path).transcribe(BytesIO(content), beam_size=5)
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
