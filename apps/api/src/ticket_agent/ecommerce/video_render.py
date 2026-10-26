import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


class StoryboardRenderError(Exception):
    pass


def render_storyboard_video(
    images: list[bytes],
    durations: list[float],
    *,
    ffmpeg_path: str,
    transition_seconds: float = 0.2,
    zoom_strength: float = 0.08,
) -> bytes:
    if not images or len(images) != len(durations):
        raise StoryboardRenderError("Storyboard images and durations must match")
    if any(duration <= 0 or duration > 30 for duration in durations):
        raise StoryboardRenderError("Storyboard duration is out of range")
    if transition_seconds < 0 or transition_seconds > 1:
        raise StoryboardRenderError("Storyboard transition is out of range")
    if zoom_strength < 0 or zoom_strength > 0.3:
        raise StoryboardRenderError("Storyboard zoom is out of range")
    with TemporaryDirectory(prefix="storyboard-video-") as directory:
        root = Path(directory)
        input_paths: list[Path] = []
        for index, image in enumerate(images, start=1):
            image_path = root / f"scene-{index}.png"
            image_path.write_bytes(image)
            input_paths.append(image_path)
        output_path = root / "storyboard.mp4"
        total_duration = sum(durations)
        command = [ffmpeg_path, "-y"]
        for image_path, duration in zip(input_paths, durations, strict=True):
            command.extend(
                [
                    "-loop",
                    "1",
                    "-t",
                    f"{duration:.3f}",
                    "-i",
                    str(image_path),
                ]
            )
        filters = []
        for index, duration in enumerate(durations):
            fade_duration = min(transition_seconds, duration / 4)
            fade_out_start = max(0.0, duration - fade_duration)
            zoom_step = zoom_strength / max(1.0, duration * 30)
            filters.append(
                
                    f"[{index}:v]scale=1080:1920:"
                    "force_original_aspect_ratio=decrease,"
                    "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=white,"
                    "setsar=1,fps=30,"
                    "zoompan=z='min(zoom+"
                    f"{zoom_step:.8f},"
                    f"{1 + zoom_strength:.4f})':"
                    "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                    "d=1:s=1080x1920:fps=30,"
                    f"fade=t=in:st=0:d={fade_duration:.3f},"
                    f"fade=t=out:st={fade_out_start:.3f}:d={fade_duration:.3f},"
                    f"format=yuv420p[v{index}]"
                
            )
        concat_inputs = "".join(f"[v{index}]" for index in range(len(input_paths)))
        filters.append(
            f"{concat_inputs}concat=n={len(input_paths)}:v=1:a=0[outv]"
        )
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[outv]",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-movflags",
            "+faststart",
            "-an",
            "-t",
            f"{total_duration:.3f}",
            str(output_path),
            ]
        )
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StoryboardRenderError(
                f"FFmpeg failed to start: {type(exc).__name__}"
            ) from exc
        if process.returncode != 0 or not output_path.exists():
            message = process.stderr.decode("utf-8", errors="replace")[-1200:]
            raise StoryboardRenderError(f"FFmpeg render failed: {message}")
        data = output_path.read_bytes()
        if len(data) < 1024:
            raise StoryboardRenderError("FFmpeg produced an empty video")
        return data


def mux_storyboard_audio(
    video: bytes,
    audio: bytes,
    *,
    ffmpeg_path: str,
    duration_seconds: float,
    background_music: bytes | None = None,
    background_music_volume: float = 0.18,
) -> bytes:
    if not video or not audio:
        raise StoryboardRenderError("Video and audio are required")
    if duration_seconds <= 0 or duration_seconds > 120:
        raise StoryboardRenderError("Audio timeline is out of range")
    if background_music_volume < 0 or background_music_volume > 1:
        raise StoryboardRenderError("Background music volume is out of range")
    with TemporaryDirectory(prefix="storyboard-audio-") as directory:
        root = Path(directory)
        video_path = root / "video.mp4"
        audio_path = root / "voiceover.wav"
        output_path = root / "storyboard-with-voice.mp4"
        video_path.write_bytes(video)
        audio_path.write_bytes(audio)
        mock_music_path = root / "background-music.bin"
        command = [
            ffmpeg_path,
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
        ]
        if background_music is not None:
            mock_music_path.write_bytes(background_music)
            command.extend(
                ["-stream_loop", "-1", "-i", str(mock_music_path)]
            )
        # loudnorm 对整段数字静音会算出 ±Inf 增益，FFmpeg 7.x 随后把 NaN
        # 送进 AAC 编码器导致整条视频渲染失败。aeval 把非有限采样归零；
        # aformat 重新声明声道布局，否则编码器不认 aeval 输出的 "2 channels"。
        loudness = (
            "loudnorm=I=-16:TP=-1.5:LRA=11,"
            "aeval=exprs='if(isnan(val(0))+isinf(val(0)),0,val(0))',"
            "aformat=sample_fmts=fltp:channel_layouts=stereo"
        )
        if background_music is None:
            audio_filter = (
                f"[1:a]aresample=48000,{loudness},aresample=48000[aout]"
            )
        else:
            audio_filter = (
                "[1:a]aresample=48000,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"{loudness},"
                "asplit=2[voice][side];"
                f"[2:a]aresample=48000,volume={background_music_volume:.3f},"
                "aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"atrim=0:{duration_seconds:.3f},asetpts=PTS-STARTPTS[music];"
                "[music][side]sidechaincompress=threshold=0.025:"
                "ratio=8:attack=20:release=400[ducked];"
                "[ducked][voice]amix=inputs=2:duration=first:"
                "dropout_transition=0,aresample=48000,"
                f"{loudness},aresample=48000[aout]"
            )
        command.extend(
            [
                "-filter_complex",
                audio_filter,
                "-map",
                "0:v:0",
                "-map",
                "[aout]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                "-shortest",
                str(output_path),
            ]
        )
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StoryboardRenderError(
                f"FFmpeg audio mux failed to start: {type(exc).__name__}"
            ) from exc
        if process.returncode != 0 or not output_path.exists():
            message = process.stderr.decode("utf-8", errors="replace")[-1200:]
            raise StoryboardRenderError(f"FFmpeg audio mux failed: {message}")
        data = output_path.read_bytes()
        if len(data) < 1024:
            raise StoryboardRenderError("FFmpeg produced an empty voiced video")
        return data


def burn_storyboard_subtitles(
    video: bytes,
    subtitles: bytes,
    *,
    font_path: Path,
    ffmpeg_path: str,
) -> bytes:
    if not video or not subtitles:
        raise StoryboardRenderError("Video and subtitles are required")
    if not font_path.is_file():
        raise StoryboardRenderError("Subtitle font is unavailable")
    with TemporaryDirectory(prefix="storyboard-subtitles-") as directory:
        root = Path(directory)
        video_path = root / "video.mp4"
        subtitle_path = root / "subtitles.vtt"
        local_font_path = root / "subtitle-font.otf"
        output_path = root / "storyboard-burned.mp4"
        video_path.write_bytes(video)
        subtitle_path.write_bytes(subtitles)
        local_font_path.write_bytes(font_path.read_bytes())
        style = (
            "FontName=Noto Sans CJK SC,FontSize=34,"
            "PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,"
            "BorderStyle=1,Outline=1.2,Shadow=0,MarginV=110,Alignment=2"
        )
        filters = (
            f"subtitles={subtitle_path}:fontsdir={root}:"
            f"force_style='{style}'"
        )
        process = subprocess.run(
            [
                ffmpeg_path,
                "-y",
                "-i",
                str(video_path),
                "-vf",
                filters,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            capture_output=True,
            check=False,
            timeout=120,
        )
        if process.returncode != 0 or not output_path.exists():
            message = process.stderr.decode("utf-8", errors="replace")[-1200:]
            raise StoryboardRenderError(
                f"FFmpeg subtitle burn-in failed: {message}"
            )
        data = output_path.read_bytes()
        if len(data) < 1024:
            raise StoryboardRenderError(
                "FFmpeg produced an empty subtitled video"
            )
        return data
