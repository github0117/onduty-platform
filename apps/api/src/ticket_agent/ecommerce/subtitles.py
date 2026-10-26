from html import escape


def build_storyboard_webvtt(
    scenes: list[tuple[float, str]],
) -> tuple[bytes, int]:
    if not scenes:
        raise ValueError("At least one subtitle scene is required")
    cues: list[str] = ["WEBVTT", ""]
    cursor = 0.0
    cue_count = 0
    for duration, text in scenes:
        if duration <= 0 or duration > 30:
            raise ValueError("Subtitle duration is out of range")
        end = cursor + duration
        normalized_text = " ".join(text.split())
        if normalized_text:
            cue_count += 1
            cues.extend(
                [
                    str(cue_count),
                    f"{_timestamp(cursor)} --> {_timestamp(end)}",
                    escape(normalized_text),
                    "",
                ]
            )
        cursor = end
    if cue_count == 0:
        raise ValueError("At least one non-empty subtitle cue is required")
    return ("\n".join(cues).rstrip() + "\n").encode("utf-8"), cue_count


def _timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"
