"""Helpers for pacing a finished reply over an SSE stream."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator

_BOUNDARY = re.compile(r"[，。！？；：,.!?;:\n]")
_WORD_CHAR = re.compile(r"[A-Za-z0-9_./:@-]")
_DEFAULT_TARGET_CHUNKS = 40
_DEFAULT_DELAY_SECONDS = 0.04
_MIN_CHUNK_CHARS = 4


def _next_boundary(text: str, end: int) -> int:
    if _WORD_CHAR.match(text[end - 1]) and _WORD_CHAR.match(text[end]):
        # Keep identifiers, numbers and URLs whole within a reasonable window.
        token_end = end
        limit = min(len(text), end + 40)
        while token_end < limit and _WORD_CHAR.match(text[token_end]):
            token_end += 1
        while token_end < len(text) and _BOUNDARY.match(text[token_end]):
            token_end += 1
        return token_end
    lookahead = min(len(text), end + 12)
    match = _BOUNDARY.search(text, end, lookahead)
    return match.end() if match is not None else end


def iter_text_chunks(
    text: str,
    *,
    target_chunks: int = _DEFAULT_TARGET_CHUNKS,
) -> Iterator[str]:
    """Split text into readable chunks without cutting inside a word."""
    if not text:
        return
    size = max(
        _MIN_CHUNK_CHARS,
        -(-len(text) // max(1, target_chunks)),
    )
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            end = _next_boundary(text, end)
        yield text[start:end]
        start = end


def stream_text(
    text: str,
    emit: Callable[[str], None],
    *,
    delay_seconds: float = _DEFAULT_DELAY_SECONDS,
    target_chunks: int = _DEFAULT_TARGET_CHUNKS,
) -> None:
    for chunk in iter_text_chunks(text, target_chunks=target_chunks):
        emit(chunk)
        if delay_seconds > 0:
            time.sleep(delay_seconds)


__all__ = ["iter_text_chunks", "stream_text"]
