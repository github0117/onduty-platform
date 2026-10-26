import re

_NUMERIC_CLAIM_PATTERNS = (
    re.compile(r"(?:¥|￥|人民币)\s?\d+(?:\.\d+)?\s?(?:元|万元)?"),
    re.compile(r"\d+(?:\.\d+)?\s?%"),
    re.compile(r"\d+\s?(?:分钟|小时|天|个工作日|工作日)"),
    re.compile(r"\d{4}[-年]\d{1,2}(?:[-月]\d{1,2}日?)?"),
)


class GroundingViolation(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_numeric_claims(
    draft_text: str,
    source_texts: list[str],
) -> None:
    source = _normalize(" ".join(source_texts))
    for pattern in _NUMERIC_CLAIM_PATTERNS:
        for match in pattern.finditer(draft_text):
            claim = _normalize(match.group(0))
            if claim not in source:
                raise GroundingViolation(
                    "UNSUPPORTED_NUMERIC_CLAIM",
                    f"Draft contains unsupported numeric commitment: {match.group(0)}",
                )


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value)

