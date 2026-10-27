import math
import re
from collections import Counter

_ZERO_WIDTH = dict.fromkeys(
    map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"),
)

_EXPLICIT_PAGE_NUMBER = re.compile(
    r"^(?:第\s*\d{1,4}\s*页|\d{1,4}\s*/\s*\d{1,4}|[-–—]\s*\d{1,4}\s*[-–—])$",
)
_BARE_NUMBER = re.compile(r"^\d{1,4}$")
_LIST_MARKER = re.compile(r"^(?:[-*•·]|\d{1,3}[.、)）]|[（(]\d{1,3}[)）])\s*")
_TERMINAL_PUNCTUATION = "。！？!?；;：:"
_JOINABLE_ASCII = re.compile(r"[A-Za-z0-9,;:'\"-]")

DEFAULT_REPEAT_RATIO = 0.5
DEFAULT_MIN_PAGES = 3
MAX_REPEATED_LINE_LENGTH = 120
LOW_QUALITY_REPLACEMENT_RATIO = 0.02


def normalize_whitespace(value: str) -> str:
    """Drop zero-width noise, normalize spaces and collapse blank runs."""
    cleaned = (
        value.translate(_ZERO_WIDTH)
        .replace("\u00a0", " ")
        .replace("\u3000", " ")
    )
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.splitlines()]
    collapsed: list[str] = []
    for line in lines:
        if line:
            collapsed.append(line)
        elif collapsed and collapsed[-1] != "":
            collapsed.append("")
    while collapsed and collapsed[-1] == "":
        collapsed.pop()
    return "\n".join(collapsed).strip()


def clean_text(value: str, *, merge_wrapped: bool = False) -> tuple[str, list[str]]:
    """Clean parser output that has no page boundaries.

    ``merge_wrapped`` joins hard-wrapped lines inside a paragraph. It is enabled
    for plain text and PDF, but left off for Markdown where line breaks are
    structural.
    """
    text = normalize_whitespace(value)
    text = _remove_explicit_page_numbers(text)
    text = _merge_hyphenated_breaks(text)
    if merge_wrapped:
        text = "\n\n".join(
            "\n".join(_merge_wrapped_lines(group.splitlines()))
            for group in text.split("\n\n")
        )
    text = normalize_whitespace(text)
    return text, quality_warnings(text)


def clean_pdf_pages(pages: list[str]) -> tuple[str, list[str]]:
    """Clean page-level text: drop repeated headers/footers and rejoin wraps.

    Pages with fewer than ``DEFAULT_MIN_PAGES`` entries are cleaned as a single
    document, because repeated-line detection needs a page distribution.
    """
    normalized_pages = [normalize_whitespace(page) for page in pages]
    if len(normalized_pages) < DEFAULT_MIN_PAGES:
        joined = "\n\n".join(page for page in normalized_pages if page)
        text, warnings = clean_text(joined, merge_wrapped=True)
        if not text:
            return "", warnings
        return text, warnings

    stripped_pages = _strip_repeated_page_artifacts(normalized_pages)
    paragraphs: list[str] = []
    for page in stripped_pages:
        lines = _drop_bare_page_numbers(page.splitlines())
        paragraphs.extend(_merge_wrapped_lines(lines))
    text, warnings = clean_text("\n\n".join(paragraphs))
    return text, warnings


def strip_repeated_page_artifacts(
    pages: list[str],
    *,
    min_pages: int = DEFAULT_MIN_PAGES,
    ratio: float = DEFAULT_REPEAT_RATIO,
) -> list[str]:
    if len(pages) < min_pages:
        return pages
    counter: Counter[str] = Counter()
    for page in pages:
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        if len(lines) < 4:
            continue
        for line in {lines[0], lines[-1]}:
            if len(line) <= MAX_REPEATED_LINE_LENGTH:
                counter[line] += 1
    threshold = max(2, math.ceil(len(pages) * ratio))
    repeated = {
        line for line, count in counter.items() if count >= threshold
    }
    if not repeated:
        return pages
    return [
        "\n".join(
            line for line in page.splitlines() if line.strip() not in repeated
        )
        for page in pages
    ]


def quality_warnings(text: str) -> list[str]:
    warnings: list[str] = []
    if not text:
        return ["CONTENT_EMPTY"]
    replacement_ratio = text.count("�") / len(text)
    if replacement_ratio > LOW_QUALITY_REPLACEMENT_RATIO:
        warnings.append("PARSE_QUALITY_LOW")
    if len(text) < 10:
        warnings.append("CONTENT_TOO_SHORT")
    return warnings


def _strip_repeated_page_artifacts(pages: list[str]) -> list[str]:
    return strip_repeated_page_artifacts(pages)


def _drop_bare_page_numbers(lines: list[str]) -> list[str]:
    if not lines:
        return lines
    kept = list(lines)
    for index in {0, len(kept) - 1}:
        if 0 <= index < len(kept) and _BARE_NUMBER.match(kept[index].strip()):
            kept[index] = ""
    return [line for line in kept if line.strip()]


def _merge_wrapped_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if merged and merged[-1] != "":
                merged.append("")
            continue
        if merged and merged[-1] and _should_join(merged[-1], stripped):
            merged[-1] = _join_lines(merged[-1], stripped)
        else:
            merged.append(stripped)
    return [line for line in merged if line]


def _should_join(previous: str, current: str) -> bool:
    if not previous or not current:
        return False
    if previous[-1] in _TERMINAL_PUNCTUATION:
        return False
    if previous.endswith(("。", "”", "」", "）", ")", "]", "】")):
        return False
    if _LIST_MARKER.match(current):
        return False
    if current.startswith(("#", ">", "|", "－", "—", "◆", "■")):
        return False
    if _EXPLICIT_PAGE_NUMBER.match(current):
        return False
    return len(previous) >= 20


def _join_lines(previous: str, current: str) -> str:
    if _JOINABLE_ASCII.match(previous[-1]) and _JOINABLE_ASCII.match(current[0]):
        return f"{previous} {current}"
    return f"{previous}{current}"


def _remove_explicit_page_numbers(value: str) -> str:
    lines = [
        line
        for line in value.splitlines()
        if not _EXPLICIT_PAGE_NUMBER.match(line.strip())
    ]
    return "\n".join(lines)


def _merge_hyphenated_breaks(value: str) -> str:
    return re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", value)
