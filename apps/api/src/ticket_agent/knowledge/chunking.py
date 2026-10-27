from dataclasses import dataclass
from typing import Any, Literal

BlockKind = Literal["heading", "paragraph", "table", "list_item"]

_SENTENCE_DELIMITERS = "。！？!?；;"


@dataclass(frozen=True)
class ChunkDraft:
    content: str
    embedding_text: str
    section_path: tuple[str, ...] = ()
    block_kinds: tuple[str, ...] = ()


def chunk_blocks(
    blocks: list[dict[str, Any]],
    *,
    target_chars: int = 800,
    max_chars: int = 1200,
) -> list[ChunkDraft]:
    """Pack structured blocks into chunks that respect headings and tables."""
    drafts: list[ChunkDraft] = []
    section_path: list[str] = []
    section_blocks: list[dict[str, Any]] = []

    def flush_section() -> None:
        if section_blocks:
            drafts.extend(
                _pack_section(
                    tuple(section_path),
                    list(section_blocks),
                    target_chars=target_chars,
                    max_chars=max_chars,
                )
            )
            section_blocks.clear()

    for block in blocks:
        kind = block.get("kind")
        text = str(block.get("text", "")).strip()
        if not text:
            continue
        if kind == "heading":
            flush_section()
            level = int(block.get("level") or 1)
            del section_path[max(level - 1, 0) :]
            section_path.append(text)
            continue
        section_blocks.append({"kind": kind, "text": text})
    flush_section()
    return drafts


def _pack_section(
    section_path: tuple[str, ...],
    blocks: list[dict[str, Any]],
    *,
    target_chars: int,
    max_chars: int,
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    buffer: list[dict[str, Any]] = []
    size = 0

    def flush() -> None:
        nonlocal size
        if not buffer:
            return
        content = "\n".join(str(item["text"]) for item in buffer).strip()
        if content:
            kinds = tuple(dict.fromkeys(str(item["kind"]) for item in buffer))
            drafts.append(_draft(section_path, content, kinds))
        buffer.clear()
        size = 0

    for block in blocks:
        text = str(block["text"])
        kind = str(block["kind"])
        if kind == "table":
            # Tables are atomic: never split rows, never share a chunk.
            flush()
            drafts.append(_draft(section_path, text, ("table",)))
            continue
        if len(text) > max_chars:
            flush()
            for piece in _split_long_text(text, target_chars=target_chars):
                drafts.append(_draft(section_path, piece, (kind,)))
            continue
        if size and size + len(text) > target_chars:
            flush()
        buffer.append(block)
        size += len(text)
    flush()
    return drafts


def _draft(
    section_path: tuple[str, ...],
    content: str,
    kinds: tuple[str, ...],
) -> ChunkDraft:
    embedding_text = (
        f"{' > '.join(section_path)}\n{content}" if section_path else content
    )
    return ChunkDraft(
        content=content,
        embedding_text=embedding_text,
        section_path=section_path,
        block_kinds=kinds,
    )


def _split_long_text(text: str, *, target_chars: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for sentence in _sentences(text):
        if current and len(current) + len(sentence) > target_chars:
            pieces.append(current.strip())
            current = ""
        if len(sentence) > target_chars:
            for start in range(0, len(sentence), target_chars):
                pieces.append(sentence[start : start + target_chars].strip())
            continue
        current += sentence
    if current.strip():
        pieces.append(current.strip())
    return [piece for piece in pieces if piece]


def _sentences(text: str) -> list[str]:
    sentences: list[str] = []
    current = ""
    for char in text:
        current += char
        if char in _SENTENCE_DELIMITERS or char == "\n":
            sentences.append(current)
            current = ""
    if current:
        sentences.append(current)
    return sentences
