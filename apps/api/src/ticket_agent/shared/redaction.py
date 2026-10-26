import re
from typing import Any

_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_MOBILE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_ID_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){16,19}(?!\d)")


def redact_sensitive_text(text: str) -> str:
    redacted = _EMAIL_PATTERN.sub("<EMAIL>", text)
    redacted = _MOBILE_PATTERN.sub("<MOBILE>", redacted)
    redacted = _ID_PATTERN.sub("<ID>", redacted)
    return _CARD_PATTERN.sub("<CARD>", redacted)


def redact_sensitive_data(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {
            str(key): redact_sensitive_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    return value

