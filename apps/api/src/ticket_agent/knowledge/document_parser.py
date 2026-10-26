import io
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree


class DocumentParseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    parser_name: str
    parser_version: str


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
        elif tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


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
        return ParsedDocument(text=text, parser_name="plain-text", parser_version="1")
    if suffix in {".html", ".htm"}:
        parser = _TextHTMLParser()
        parser.feed(_decode_text(data))
        text = _normalize_text("".join(parser.parts))
        return ParsedDocument(text=text, parser_name="html-parser", parser_version="1")
    if suffix == ".docx":
        text = _parse_docx(data)
        return ParsedDocument(text=text, parser_name="docx-xml", parser_version="1")
    if suffix == ".pdf":
        return ParsedDocument(
            text=_parse_pdf(data),
            parser_name="pypdf",
            parser_version=_pypdf_version(),
        )

    raise DocumentParseError(
        "UNSUPPORTED_DOCUMENT_TYPE",
        f"Unsupported document type: {suffix or content_type}",
    )


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return _normalize_text(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    raise DocumentParseError("TEXT_DECODE_FAILED", "Unable to decode text document.")


def _parse_docx(data: bytes) -> str:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise DocumentParseError("INVALID_DOCX", "DOCX document is invalid.") from exc

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise DocumentParseError("INVALID_DOCX", "DOCX XML is invalid.") from exc

    paragraphs: list[str] = []
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    for paragraph in root.iter(f"{{{namespace}}}p"):
        parts = [
            node.text or ""
            for node in paragraph.iter(f"{{{namespace}}}t")
        ]
        if parts:
            paragraphs.append("".join(parts))
    text = _normalize_text("\n".join(paragraphs))
    if not text:
        raise DocumentParseError("EMPTY_DOCUMENT", "DOCX contains no extractable text.")
    return text


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
    text = _normalize_text("\n".join(pages))
    if not text:
        raise DocumentParseError("EMPTY_DOCUMENT", "PDF contains no extractable text.")
    return text


def _pypdf_version() -> str:
    try:
        import pypdf
    except ImportError:
        return "unavailable"
    return str(pypdf.__version__)


def _normalize_text(value: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()

