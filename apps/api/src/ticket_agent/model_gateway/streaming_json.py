"""Incremental extraction of a string field from streamed JSON.

Model providers stream the draft as JSON deltas. The customer only needs the
top-level ``text`` field, so this parser decodes that field as it arrives
instead of buffering the whole document.
"""

from __future__ import annotations

_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


class JsonStringFieldExtractor:
    def __init__(self, field_name: str = "text") -> None:
        self._field_name = field_name
        self._depth = 0
        self._in_string = False
        self._string_role: str | None = None
        self._string_chars: list[str] = []
        self._last_key: str | None = None
        self._expect_key = False
        self._value_is_target = False
        self._target_started = False
        self._target_finished = False
        self._escape_next = False
        self._unicode_remaining = 0
        self._unicode_chars: list[str] = []

    @property
    def target_started(self) -> bool:
        return self._target_started

    @property
    def target_finished(self) -> bool:
        return self._target_finished

    def feed(self, chunk: str) -> str:
        """Feed raw JSON text and return any newly decoded target characters."""
        emitted: list[str] = []
        for char in chunk:
            emitted.extend(self._consume(char))
        return "".join(emitted)

    def _consume(self, char: str) -> list[str]:
        if self._in_string:
            return self._consume_string_char(char)
        if char == '"':
            self._begin_string()
            return []
        if char in "{[":
            self._depth += 1
            if char == "{" and self._depth == 1:
                self._expect_key = True
            return []
        if char in "}]":
            self._depth = max(0, self._depth - 1)
            return []
        if self._depth == 1:
            if char == ",":
                self._expect_key = True
                self._value_is_target = False
            elif char == ":":
                self._expect_key = False
                self._value_is_target = self._last_key == self._field_name
        return []

    def _begin_string(self) -> None:
        self._in_string = True
        self._string_chars = []
        self._escape_next = False
        self._unicode_remaining = 0
        self._unicode_chars = []
        if self._depth != 1:
            self._string_role = "other"
        elif self._expect_key:
            self._string_role = "key"
        elif self._value_is_target:
            self._string_role = "target"
            self._target_started = True
        else:
            self._string_role = "other"

    def _consume_string_char(self, char: str) -> list[str]:
        if self._unicode_remaining:
            self._unicode_chars.append(char)
            self._unicode_remaining -= 1
            if self._unicode_remaining:
                return []
            try:
                decoded = chr(int("".join(self._unicode_chars), 16))
            except ValueError:
                decoded = ""
            self._unicode_chars = []
            return self._append_decoded(decoded)
        if self._escape_next:
            self._escape_next = False
            if char == "u":
                self._unicode_remaining = 4
                self._unicode_chars = []
                return []
            return self._append_decoded(_ESCAPES.get(char, char))
        if char == "\\":
            self._escape_next = True
            return []
        if char == '"':
            self._end_string()
            return []
        return self._append_decoded(char)

    def _append_decoded(self, char: str) -> list[str]:
        if self._string_role == "target":
            return [char]
        if self._string_role == "key":
            self._string_chars.append(char)
        return []

    def _end_string(self) -> None:
        role = self._string_role
        self._in_string = False
        self._string_role = None
        if role == "key":
            self._last_key = "".join(self._string_chars)
            self._expect_key = False
            self._value_is_target = False
        elif role == "target":
            self._target_finished = True
            self._value_is_target = False
        elif self._depth == 1 and self._last_key == self._field_name:
            # A non-string value for the target field cannot be streamed as
            # text; stop tracking once the object moves on.
            self._value_is_target = False
        self._string_chars = []


__all__ = ["JsonStringFieldExtractor"]
