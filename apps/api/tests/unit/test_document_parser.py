import io
import zipfile

import pytest

from ticket_agent.knowledge.document_parser import DocumentParseError, parse_document


def _docx_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{namespace}"><w:body><w:p><w:r><w:t>'
        f"{text}"
        "</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def test_parse_html_excludes_scripts() -> None:
    parsed = parse_document(
        filename="guide.html",
        content_type="text/html",
        data=(
            b"<html><body><h1>Auth</h1><p>How to configure.</p>"
            b"<script>ignore()</script></body></html>"
        ),
        max_bytes=1024,
    )

    assert "Auth" in parsed.text
    assert "How to configure." in parsed.text
    assert "ignore" not in parsed.text


def test_parse_docx_extracts_paragraph_text() -> None:
    parsed = parse_document(
        filename="guide.docx",
        content_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        data=_docx_bytes("How to configure notifications."),
        max_bytes=1024,
    )

    assert parsed.text == "How to configure notifications."
    assert parsed.parser_name == "docx-xml"


def test_reject_oversized_document() -> None:
    with pytest.raises(DocumentParseError) as error:
        parse_document(
            filename="large.txt",
            content_type="text/plain",
            data=b"x" * 20,
            max_bytes=10,
        )

    assert error.value.code == "FILE_TOO_LARGE"


def test_reject_unsupported_extension() -> None:
    with pytest.raises(DocumentParseError) as error:
        parse_document(
            filename="archive.zip",
            content_type="application/zip",
            data=b"PK",
            max_bytes=1024,
        )

    assert error.value.code == "UNSUPPORTED_DOCUMENT_TYPE"

