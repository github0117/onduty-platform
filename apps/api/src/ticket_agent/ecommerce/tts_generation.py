import io
import wave
from dataclasses import dataclass
from typing import Protocol

import httpx

from ticket_agent.shared.redaction import redact_sensitive_text
from ticket_agent.shared.settings import Settings, get_settings


class TTSGenerationError(Exception):
    pass


@dataclass(frozen=True)
class GeneratedSpeech:
    data: bytes
    content_type: str
    provider: str
    model_name: str
    voice: str


class SpeechGenerator(Protocol):
    def generate(self, *, text: str) -> GeneratedSpeech: ...


class DashScopeQwenSpeechGenerator:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self._client = client or httpx.Client(
            timeout=settings.ecommerce_tts_timeout_seconds,
            follow_redirects=True,
        )

    def generate(self, *, text: str) -> GeneratedSpeech:
        api_key = (
            self.settings.ecommerce_content_api_key
            or self.settings.model_api_key
        )
        if not api_key or not self.settings.ecommerce_tts_model_name:
            raise TTSGenerationError(
                "TTS API key and model name are required"
            )
        safe_text = (
            redact_sensitive_text(text)
            if self.settings.model_data_redaction_enabled
            else text
        )
        response = self._client.post(
            (
                "https://dashscope.aliyuncs.com/api/v1/services/"
                "aigc/multimodal-generation/generation"
            ),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.ecommerce_tts_model_name,
                "input": {
                    "text": safe_text,
                    "voice": self.settings.ecommerce_tts_voice,
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        output = payload.get("output")
        audio = output.get("audio") if isinstance(output, dict) else None
        audio_url = audio.get("url") if isinstance(audio, dict) else None
        if not isinstance(audio_url, str) or not audio_url.startswith("http"):
            raise TTSGenerationError("TTS response audio URL is missing")
        audio_response = self._client.get(audio_url)
        audio_response.raise_for_status()
        data = audio_response.content
        if not data.startswith(b"RIFF") or len(data) < 1000:
            raise TTSGenerationError("TTS response is not a valid WAV file")
        return GeneratedSpeech(
            data=data,
            content_type="audio/wav",
            provider="dashscope_qwen",
            model_name=self.settings.ecommerce_tts_model_name,
            voice=self.settings.ecommerce_tts_voice,
        )


def get_speech_generator(
    settings: Settings | None = None,
) -> SpeechGenerator | None:
    resolved = settings or get_settings()
    if resolved.ecommerce_tts_provider == "dashscope_qwen":
        return DashScopeQwenSpeechGenerator(resolved)
    return None


def assemble_scene_audio(
    tracks: list[bytes],
    durations: list[float],
) -> bytes:
    if not tracks or len(tracks) != len(durations):
        raise TTSGenerationError("Voice tracks and durations must match")
    output = io.BytesIO()
    output_params: tuple[int, int, int] | None = None
    with wave.open(output, "wb") as destination:
        for track, duration in zip(tracks, durations, strict=True):
            try:
                with wave.open(io.BytesIO(track), "rb") as source:
                    params = source.getparams()
                    if output_params is None:
                        output_params = (
                            params.nchannels,
                            params.sampwidth,
                            params.framerate,
                        )
                        destination.setparams(params)
                    if (
                        params.nchannels,
                        params.sampwidth,
                        params.framerate,
                    ) != output_params:
                        raise TTSGenerationError(
                            "Voice tracks use inconsistent WAV formats"
                        )
                    frame_size = params.nchannels * params.sampwidth
                    wanted_frames = max(1, round(duration * params.framerate))
                    frames = source.readframes(wanted_frames)
                    missing_bytes = wanted_frames * frame_size - len(frames)
                    if missing_bytes > 0:
                        frames += b"\x00" * missing_bytes
                    destination.writeframes(frames)
            except wave.Error as exc:
                raise TTSGenerationError("Voice track is not valid WAV") from exc
    return output.getvalue()
