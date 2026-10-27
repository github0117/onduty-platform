"""Query rewriting for knowledge retrieval.

Two layers, both independently switchable:

* Context resolution (``KNOWLEDGE_QUERY_CONTEXT_ENABLED``): rule-based, no
  model. A follow-up question such as "那退款呢" is turned into a standalone
  query by resolving pronouns against the latest conversation turns. The
  original query is kept as a second retrieval channel so a wrong resolution
  cannot silently drop a match that already worked.
* LLM multi-query expansion (``KNOWLEDGE_QUERY_REWRITE_ENABLED``): only called
  when the best local score is below the trigger threshold. Failures fall back
  to the un-rewritten result and are counted, never surfaced as a 5xx.

The module is deliberately free of database access so it can be unit tested
without a session.
"""

import json
import logging
import re
from dataclasses import dataclass
from threading import Lock
from typing import Protocol, cast

import httpx

from ticket_agent.knowledge.tokenizer import MAX_QUERY_TOKENS, tokenize
from ticket_agent.shared.redaction import redact_sensitive_text
from ticket_agent.shared.settings import Settings

logger = logging.getLogger(__name__)

# Longest history message copied into a standalone query.
MAX_HISTORY_MESSAGE_CHARS = 300
MAX_STANDALONE_CHARS = 800
MAX_REWRITTEN_VARIANT_CHARS = 300

# Longest alternatives first so "这个" is not matched as "这".
_ANAPHORA_PATTERN = re.compile(
    r"(它们|这些|那些|这个|那个|这款|那款|该款|上述|上面|它|该|此|这|那)"
)
# Latin model numbers, SKUs and order numbers worth resolving a pronoun to.
_ENTITY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\d[A-Za-z0-9._/-]*")
# Leading list markers from a model that answered as a bullet list.
_LIST_MARKER_PATTERN = re.compile(r"^(?:[-*•]|\d+[.)、])\s*")

_LOCK = Lock()
_REWRITES = 0
_FALLBACKS = 0


def query_rewrite_total() -> int:
    """Successful LLM rewrites that added at least one variant."""

    with _LOCK:
        return _REWRITES


def query_rewrite_fallback_total() -> int:
    """LLM rewrite calls that failed and kept the local results."""

    with _LOCK:
        return _FALLBACKS


def record_query_rewrite() -> None:
    global _REWRITES
    with _LOCK:
        _REWRITES += 1


def record_query_rewrite_fallback() -> None:
    global _FALLBACKS
    with _LOCK:
        _FALLBACKS += 1


def reset_query_rewrite_metrics() -> None:
    """Reset both counters. Intended for tests and the demo reset."""

    global _REWRITES, _FALLBACKS
    with _LOCK:
        _REWRITES = 0
        _FALLBACKS = 0


class QueryRewriteError(RuntimeError):
    """The rewriter could not produce usable variants."""


class QueryRewriteProvider(Protocol):
    @property
    def name(self) -> str: ...

    def rewrite(self, *, query: str, variants: int) -> list[str]: ...


@dataclass(frozen=True)
class QueryResolution:
    original: str
    standalone: str
    context_used: bool


def build_search_queries(
    query: str,
    history: list[str] | None,
    *,
    max_history_turns: int,
    enabled: bool,
) -> list[str]:
    """Return the queries to retrieve with, most specific last.

    ``history`` holds earlier user turns, oldest first. It must not contain the
    current ``query``. When no anaphora is present, or the setting is off, the
    original query is the only channel and behaviour matches the pre-rewrite
    implementation exactly.
    """
    if not enabled or not history:
        return [query]
    resolution = resolve_query(
        query,
        history,
        max_history_turns=max_history_turns,
    )
    if not resolution.context_used:
        return [query]
    if resolution.standalone.casefold() == query.strip().casefold():
        return [query]
    return [query, resolution.standalone]


def resolve_query(
    query: str,
    history: list[str] | None,
    *,
    max_history_turns: int = 3,
) -> QueryResolution:
    """Resolve pronouns in ``query`` against the most recent user turns."""
    stripped = query.strip()
    recent = _recent_history(history, max_history_turns)
    if not stripped or not recent or not _ANAPHORA_PATTERN.search(stripped):
        return QueryResolution(original=query, standalone=query, context_used=False)

    entity = _nearest_entity(recent)
    if entity is not None:
        standalone = _ANAPHORA_PATTERN.sub(entity, stripped, count=1)
    else:
        # No concrete code or number to substitute: prepend the previous turn
        # so the embedding sees both the anaphora and its antecedent.
        standalone = f"{recent[-1]}\n{stripped}"
    standalone = standalone[:MAX_STANDALONE_CHARS].strip()
    return QueryResolution(
        original=query,
        standalone=standalone,
        context_used=standalone != stripped,
    )


def extract_keywords(text: str, *, limit: int = MAX_QUERY_TOKENS) -> str:
    """Deduplicated lexical terms used by the BM25-style channel.

    ``build_tsquery`` tokenises again; passing the already-deduplicated terms
    keeps the tsquery short without changing the vocabulary.
    """
    seen: list[str] = []
    for token in tokenize(text):
        if token in seen:
            continue
        seen.append(token)
        if len(seen) >= limit:
            break
    return " ".join(seen)


def _recent_history(
    history: list[str] | None,
    max_history_turns: int,
) -> list[str]:
    if not history or max_history_turns < 1:
        return []
    cleaned = [
        " ".join(item.split())[:MAX_HISTORY_MESSAGE_CHARS]
        for item in history
        if isinstance(item, str) and item.strip()
    ]
    return cleaned[-max_history_turns:]


def _nearest_entity(messages: list[str]) -> str | None:
    for message in reversed(messages):
        matches: list[str] = _ENTITY_PATTERN.findall(message)
        if matches:
            return matches[-1]
    return None


class OpenAICompatibleQueryRewriter:
    """Low-latency LLM expansion over an OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self._client = client or httpx.Client(
            timeout=settings.knowledge_query_rewrite_timeout_seconds
        )

    @property
    def name(self) -> str:
        return f"external:{self.settings.query_rewrite_model_name}"

    def rewrite(self, *, query: str, variants: int) -> list[str]:
        count = max(1, variants)
        try:
            response = self._client.post(
                f"{self.settings.query_rewrite_base_url.rstrip('/')}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.settings.query_rewrite_model_name,
                    "temperature": 0,
                    "max_tokens": 320,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Rewrite the user's search query into "
                                f"{count} alternative queries. Return only a "
                                "JSON array of strings. Keep product model "
                                "numbers, order numbers and the original "
                                "language unchanged. Do not answer the query."
                            ),
                        },
                        {"role": "user", "content": query},
                    ],
                },
            )
            response.raise_for_status()
            content = cast(
                object,
                response.json()["choices"][0]["message"]["content"],
            )
        except (
            httpx.HTTPError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as exc:
            raise QueryRewriteError(
                f"query rewrite request failed: {type(exc).__name__}"
            ) from exc

        cleaned = sanitize_variants(
            _parse_variants(content),
            original=query,
            limit=count,
        )
        if not cleaned:
            raise QueryRewriteError("query rewrite returned no usable variants")
        return cleaned

    def _headers(self) -> dict[str, str]:
        if not self.settings.query_rewrite_api_key:
            return {}
        return {
            "Authorization": f"Bearer {self.settings.query_rewrite_api_key}"
        }


def _parse_variants(content: object) -> list[object]:
    if not isinstance(content, str):
        return []
    text = content.strip()
    parsed = _loads(text)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("queries", "variants"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
    match = re.search(r"\[.*\]", text, re.S)
    if match is not None:
        parsed = _loads(match.group(0))
        if isinstance(parsed, list):
            return parsed
    return cast(list[object], text.splitlines())


def _loads(value: str) -> object | None:
    try:
        return cast(object, json.loads(value))
    except (json.JSONDecodeError, TypeError):
        return None


def _variant_text(item: object) -> str | None:
    """Accept either a plain string or a model's ``{"query": ...}`` object."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("query", "text", "rewrite"):
            value = item.get(key)
            if isinstance(value, str):
                return value
    return None


def sanitize_variants(
    items: list[object],
    *,
    original: str,
    limit: int,
) -> list[str]:
    """Keep short, distinct, non-empty strings that differ from the original."""
    normalized_original = " ".join(original.split()).casefold()
    seen = {normalized_original}
    variants: list[str] = []
    for item in items:
        text = _variant_text(item)
        if text is None:
            continue
        cleaned = _LIST_MARKER_PATTERN.sub("", text.strip())
        cleaned = " ".join(cleaned.strip("\"'“”「」").split())
        cleaned = cleaned[:MAX_REWRITTEN_VARIANT_CHARS]
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        variants.append(cleaned)
        if len(variants) >= limit:
            break
    return variants


def build_query_rewriter(
    settings: Settings,
    *,
    client: httpx.Client | None = None,
) -> QueryRewriteProvider | None:
    """Build the LLM rewriter only when it is enabled and fully configured."""
    if not settings.knowledge_query_rewrite_enabled:
        return None
    if not settings.query_rewrite_base_url or not settings.query_rewrite_model_name:
        logger.warning(
            "knowledge query rewrite enabled but endpoint or model is missing"
        )
        return None
    return OpenAICompatibleQueryRewriter(settings, client=client)


def log_rewrite_fallback(exc: Exception, *, query: str) -> None:
    logger.warning(
        "knowledge query rewrite failed, keeping local result: %s: %s (query=%s)",
        type(exc).__name__,
        exc,
        redact_sensitive_text(query)[:200],
    )
