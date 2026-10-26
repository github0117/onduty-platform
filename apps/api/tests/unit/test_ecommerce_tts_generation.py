import io
import json
import wave

import httpx

from ticket_agent.ecommerce.tts_generation import (
    DashScopeQwenSpeechGenerator,
    assemble_scene_audio,
)
from ticket_agent.shared.settings import Settings


def _wav_bytes(seconds: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24_000)
        output.writeframes(b"\x00\x00" * round(24_000 * seconds))
    return buffer.getvalue()


def test_qwen_tts_generates_and_downloads_wav() -> None:
    audio = _wav_bytes(2)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["model"] == "qwen3-tts-flash"
            assert payload["input"]["voice"] == "Cherry"
            return httpx.Response(
                200,
                json={
                    "output": {
                        "audio": {"url": "https://audio.example/voice.wav"}
                    }
                },
            )
        return httpx.Response(
            200,
            content=audio,
            headers={"Content-Type": "audio/x-wav"},
        )

    generator = DashScopeQwenSpeechGenerator(
        Settings(
            ecommerce_tts_provider="dashscope_qwen",
            ecommerce_tts_model_name="qwen3-tts-flash",
            ecommerce_tts_voice="Cherry",
            ecommerce_content_api_key="shared-key",
        ),
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
        ),
    )

    result = generator.generate(text="欢迎选购雪地靴")

    assert result.data == audio
    assert result.provider == "dashscope_qwen"
    assert result.model_name == "qwen3-tts-flash"
    assert result.voice == "Cherry"


def test_assemble_scene_audio_matches_video_duration() -> None:
    audio = assemble_scene_audio(
        [_wav_bytes(1), _wav_bytes(4)],
        [3.0, 2.0],
    )

    with wave.open(io.BytesIO(audio), "rb") as output:
        duration = output.getnframes() / output.getframerate()

    assert duration == 5.0
