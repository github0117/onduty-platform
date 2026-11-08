import io
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree

from ticket_agent.knowledge.text_cleaning import (
    clean_pdf_pages,
    clean_text,
    normalize_whitespace,
)

BlockKind = Literal["heading", "paragraph", "table", "list_item"]

_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_PARAGRAPH_TAGS = {
    "p",
    "div",
    "pre",
    "blockquote",
    "section",
    "article",
    "header",
    "main",
}
_IGNORED_TAGS = {
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "aside",
    "template",
    "svg",
}
_HEADING_STYLE = re.compile(r"(?:heading|标题)\s*([1-6])", re.IGNORECASE)
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_MARKDOWN_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+(.+)$")


class DocumentParseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TextBlock:
    kind: BlockKind
    text: str
    level: int = 0


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    parser_name: str
    parser_version: str
    blocks: tuple[TextBlock, ...] = ()
    warnings: tuple[str, ...] = ()


def parse_document(
    *,
    filename: str,
    content_type: str,
    data: bytes,
    max_bytes: int,
) -> ParsedDocument:
    if len(data) > max_bytes:
        raise DocumentParseError(
            "FILE_TOO_LARGE",
            f"Document exceeds the {max_bytes} byte limit.",
        )
    if not data:
        raise DocumentParseError("EMPTY_FILE", "Document is empty.")

    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        text = _decode_text(data)
        blocks, warnings = _parse_text_document(text, markdown=suffix != ".txt")
        parser_name = "markdown" if suffix != ".txt" else "plain-text"
        return _parsed(blocks, warnings, parser_name=parser_name)
    if suffix in {".html", ".htm"}:
        parser = _StructuredHTMLParser()
        parser.feed(_decode_text(data))
        parser.close()
        blocks = parser.blocks
        return _parsed(blocks, [], parser_name="html-parser")
    if suffix == ".docx":
        blocks = _parse_docx_blocks(data)
        return _parsed(blocks, [], parser_name="docx-xml")
    if suffix == ".pdf":
        text = _parse_pdf(data)
        return _parsed(
            _paragraph_blocks(text),
            [],
            parser_name="pypdf",
            parser_version=_pypdf_version(),
        )

    raise DocumentParseError(
        "UNSUPPORTED_DOCUMENT_TYPE",
        f"Unsupported document type: {suffix or content_type}",
    )


def render_blocks(blocks: list[TextBlock] | tuple[TextBlock, ...]) -> str:
    rendered: list[str] = []
    list_buffer: list[str] = []
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        if block.kind == "list_item":
            list_buffer.append(text)
            continue
        if list_buffer:
            rendered.append("\n".join(list_buffer))
            list_buffer = []
        rendered.append(text)
    if list_buffer:
        rendered.append("\n".join(list_buffer))
    return "\n\n".join(rendered)


def serialize_blocks(
    blocks: tuple[TextBlock, ...],
    warnings: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "version": 1,
        "blocks": [
            {"kind": block.kind, "text": block.text, "level": block.level}
            for block in blocks
        ],
        "warnings": list(warnings),
    }


def _parsed(
    blocks: list[TextBlock],
    warnings: list[str],
    *,
    parser_name: str,
    parser_version: str = "2",
) -> ParsedDocument:
    usable = [block for block in blocks if block.text.strip()]
    if not usable:
        raise DocumentParseError("EMPTY_DOCUMENT", "Document contains no extractable text.")
    return ParsedDocument(
        text=render_blocks(usable),
        parser_name=parser_name,
        parser_version=parser_version,
        blocks=tuple(usable),
        warnings=tuple(warnings),
    )


class _StructuredHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[TextBlock] = []
        self._ignored_depth = 0
        self._buffer: list[str] = []
        self._kind: BlockKind = "paragraph"
        self._heading_level = 0
        self._table_rows: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in _IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if self._table_rows is not None:
            self._start_table_tag(tag)
            return
        if tag in _HEADING_TAGS:
            self._emit()
            self._kind = "heading"
            self._heading_level = int(tag[1])
            return
        if tag == "table":
            self._emit()
            self._table_rows = []
            return
        if tag == "li":
            self._emit()
            self._kind = "list_item"
            return
        if tag in _PARAGRAPH_TAGS:
            self._emit()
            self._kind = "paragraph"
            return
        if tag == "br":
            self._buffer.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _IGNORED_TAGS:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if self._table_rows is not None:
            self._end_table_tag(tag)
            return
        if tag in _HEADING_TAGS:
            self._emit()
            self._kind = "paragraph"
            self._heading_level = 0
            return
        if tag == "li":
            self._emit()
            self._kind = "paragraph"
            return
        if tag in _PARAGRAPH_TAGS:
            self._emit()

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._cell is not None:
            self._cell.append(data)
            return
        self._buffer.append(data)

    def _start_table_tag(self, tag: str) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"}:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def _end_table_tag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None:
            cell_text = normalize_whitespace("".join(self._cell))
            if self._row is not None:
                self._row.append(cell_text)
            self._cell = None
            return
        if tag == "tr" and self._row is not None:
            if self._table_rows is not None and any(cell for cell in self._row):
                self._table_rows.append(self._row)
            self._row = None
            return
        if tag == "table" and self._table_rows is not None:
            rows = self._table_rows
            self._table_rows = None
            if rows:
                self.blocks.append(
                    TextBlock(
                        kind="table",
                        text="\n".join(" | ".join(row) for row in rows),
                    )
                )

    def _emit(self) -> None:
        text = normalize_whitespace("".join(self._buffer))
        self._buffer = []
        if not text:
            return
        self.blocks.append(
            TextBlock(kind=self._kind, text=text, level=self._heading_level)
        )


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentParseError("TEXT_DECODE_FAILED", "Unable to decode text document.")


def _parse_text_document(
    text: str,
    *,
    markdown: bool,
) -> tuple[list[TextBlock], list[str]]:
    cleaned, warnings = clean_text(text, merge_wrapped=not markdown)
    if not cleaned:
        raise DocumentParseError("EMPTY_DOCUMENT", "Document contains no extractable text.")
    blocks = _markdown_blocks(cleaned) if markdown else _paragraph_blocks(cleaned)
    return blocks, warnings


def _paragraph_blocks(text: str) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    for group in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in group.splitlines() if line.strip()]
        if not lines:
            continue
        if all(_MARKDOWN_LIST_ITEM.match(line) for line in lines):
            for line in lines:
                match = _MARKDOWN_LIST_ITEM.match(line)
                blocks.append(
                    TextBlock(kind="list_item", text=match.group(1) if match else line)
                )
            continue
        blocks.append(TextBlock(kind="paragraph", text="\n".join(lines)))
    return blocks


def _markdown_blocks(text: str) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    paragraph: list[str] = []
    lines = text.splitlines()
    index = 0

    def flush() -> None:
        if paragraph:
            blocks.append(
                TextBlock(kind="paragraph", text="\n".join(paragraph).strip())
            )
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            flush()
            index += 1
            continue
        heading = _MARKDOWN_HEADING.match(stripped)
        if heading:
            flush()
            blocks.append(
                TextBlock(
                    kind="heading",
                    text=heading.group(2).strip(),
                    level=len(heading.group(1)),
                )
            )
            index += 1
            continue
        if stripped.startswith("```"):
            flush()
            fence: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                fence.append(lines[index])
                index += 1
            index += 1
            if fence:
                blocks.append(
                    TextBlock(kind="paragraph", text="\n".join(fence).strip())
                )
            continue
        if stripped.startswith("|"):
            flush()
            rows: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = lines[index].strip()
                if not re.fullmatch(r"\|?[\s:|-]+\|?", row):
                    rows.append(row)
                index += 1
            if rows:
                blocks.append(TextBlock(kind="table", text="\n".join(rows)))
            continue
        item = _MARKDOWN_LIST_ITEM.match(stripped)
        if item:
            flush()
            blocks.append(TextBlock(kind="list_item", text=item.group(1).strip()))
            index += 1
            continue
        paragraph.append(stripped)
        index += 1
    flush()
    return blocks


def _parse_docx_blocks(data: bytes) -> list[TextBlock]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise DocumentParseError("INVALID_DOCX", "DOCX document is invalid.") from exc

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise DocumentParseError("INVALID_DOCX", "DOCX XML is invalid.") from exc

    body = root.find(f"{{{_WORD_NAMESPACE}}}body")
    if body is None:
        raise DocumentParseError("EMPTY_DOCUMENT", "DOCX contains no extractable text.")
    blocks: list[TextBlock] = []
    _walk_docx_body(body, blocks)
    return blocks


def _walk_docx_body(element: ElementTree.Element, blocks: list[TextBlock]) -> None:
    paragraph_tag = f"{{{_WORD_NAMESPACE}}}p"
    table_tag = f"{{{_WORD_NAMESPACE}}}tbl"
    for child in element:
        if child.tag == paragraph_tag:
            block = _docx_paragraph_block(child)
            if block is not None:
                blocks.append(block)
        elif child.tag == table_tag:
            rows = _docx_table_rows(child)
            if rows:
                blocks.append(
                    TextBlock(
                        kind="table",
                        text="\n".join(" | ".join(row) for row in rows),
                    )
                )
        elif child.tag in {
            f"{{{_WORD_NAMESPACE}}}sdt",
            f"{{{_WORD_NAMESPACE}}}sdtContent",
        }:
            _walk_docx_body(child, blocks)


def _docx_paragraph_block(paragraph: ElementTree.Element) -> TextBlock | None:
    text = "".join(
        node.text or ""
        for node in paragraph.iter(f"{{{_WORD_NAMESPACE}}}t")
    ).strip()
    if not text:
        return None
    level = _docx_heading_level(paragraph)
    if level:
        return TextBlock(kind="heading", text=text, level=level)
    if paragraph.find(f"{{{_WORD_NAMESPACE}}}pPr/{{{_WORD_NAMESPACE}}}numPr") is not None:
        return TextBlock(kind="list_item", text=text)
    return TextBlock(kind="paragraph", text=text)


def _docx_heading_level(paragraph: ElementTree.Element) -> int:
    style = paragraph.find(
        f"{{{_WORD_NAMESPACE}}}pPr/{{{_WORD_NAMESPACE}}}pStyle"
    )
    if style is None:
        return 0
    value = style.get(f"{{{_WORD_NAMESPACE}}}val") or ""
    match = _HEADING_STYLE.search(value)
    if match:
        return int(match.group(1))
    if value.lower() == "title":
        return 1
    return 0


def _docx_table_rows(table: ElementTree.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.findall(f"{{{_WORD_NAMESPACE}}}tr"):
        cells: list[str] = []
        for cell in row.findall(f"{{{_WORD_NAMESPACE}}}tc"):
            text = " ".join(
                "".join(node.text or "" for node in paragraph.iter(f"{{{_WORD_NAMESPACE}}}t"))
                for paragraph in cell.iter(f"{{{_WORD_NAMESPACE}}}p")
            ).strip()
            cells.append(text)
        if any(cells):
            rows.append(cells)
    return rows


def _parse_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentParseError(
            "PDF_PARSER_UNAVAILABLE",
            "PDF support requires the optional pypdf package.",
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise DocumentParseError("INVALID_PDF", "PDF document could not be parsed.") from exc
    text, _warnings = clean_pdf_pages(pages)
    if not text:
        raise DocumentParseError("EMPTY_DOCUMENT", "PDF contains no extractable text.")
    return text


def _pypdf_version() -> str:
    try:
        import pypdf
    except ImportError:
        return "unavailable"
    return str(pypdf.__version__)
