import io
import json
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from ticket_agent.ecommerce.video_render import (
    mux_storyboard_audio,
    render_storyboard_video,
)
from ticket_agent.shared.settings import get_settings

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff"
    b"\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg and ffprobe are required for video rendering",
)
def test_storyboard_video_matches_scripted_duration(tmp_path: Path) -> None:
    video = render_storyboard_video(
        [TINY_PNG, TINY_PNG, TINY_PNG],
        [3.0, 5.0, 7.0],
        ffmpeg_path=get_settings().ecommerce_ffmpeg_path,
    )
    output_path = tmp_path / "storyboard.mp4"
    output_path.write_bytes(video)

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-show_entries",
            "stream=codec_name,width,height",
            "-of",
            "json",
            str(output_path),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    metadata = json.loads(probe.stdout)

    assert float(metadata["format"]["duration"]) == pytest.approx(15.0, abs=0.05)
    assert metadata["streams"][0]["codec_name"] == "h264"
    assert metadata["streams"][0]["width"] == 1080
    assert metadata["streams"][0]["height"] == 1920


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg and ffprobe are required for audio muxing",
)
def test_storyboard_audio_is_normalized_to_48khz(
    tmp_path: Path,
) -> None:
    video = render_storyboard_video(
        [TINY_PNG],
        [1.0],
        ffmpeg_path=get_settings().ecommerce_ffmpeg_path,
    )
    audio_buffer = io.BytesIO()
    with wave.open(audio_buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24_000)
        output.writeframes(b"\x00\x00" * 24_000)
    music_buffer = io.BytesIO()
    with wave.open(music_buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(44_100)
        output.writeframes(b"\x00\x00" * 22_050)
    voiced = mux_storyboard_audio(
        video,
        audio_buffer.getvalue(),
        ffmpeg_path=get_settings().ecommerce_ffmpeg_path,
        duration_seconds=1.0,
        background_music=music_buffer.getvalue(),
        background_music_volume=0.18,
    )
    output_path = tmp_path / "voiced.mp4"
    output_path.write_bytes(voiced)
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels",
            "-of",
            "json",
            str(output_path),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]

    assert stream["codec_name"] == "aac"
    assert stream["sample_rate"] == "48000"
    assert stream["channels"] == 2
