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


def test_parse_pdf_blank_document_reports_empty() -> None:
    from pypdf import PdfWriter

    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buffer)

    with pytest.raises(DocumentParseError) as error:
        parse_document(
            filename="blank.pdf",
            content_type="application/pdf",
            data=buffer.getvalue(),
            max_bytes=4096,
        )

    assert error.value.code == "EMPTY_DOCUMENT"


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


def test_markdown_preserves_heading_and_table_structure() -> None:
    parsed = parse_document(
        filename="sop.md",
        content_type="text/markdown",
        data=(
            "# 退款政策\n\n"
            "客户签收后 7 天内可以申请退款。\n\n"
            "| 类型 | 时限 |\n| --- | --- |\n| 仅退款 | 24 小时 |\n\n"
            "- 需要提供订单号\n"
        ).encode(),
        max_bytes=4096,
    )

    kinds = [block.kind for block in parsed.blocks]
    assert "heading" in kinds
    assert "table" in kinds
    assert "list_item" in kinds

    heading = next(block for block in parsed.blocks if block.kind == "heading")
    assert heading.level == 1
    assert heading.text == "退款政策"

    table = next(block for block in parsed.blocks if block.kind == "table")
    assert "仅退款 | 24 小时" in table.text
    assert parsed.parser_name == "markdown"


def test_html_ignores_navigation_and_extracts_table() -> None:
    parsed = parse_document(
        filename="faq.html",
        content_type="text/html",
        data=(
            b"<html><body><nav>menu</nav><h2>FAQ</h2><p>answer</p>"
            b"<table><tr><th>a</th><th>b</th></tr>"
            b"<tr><td>1</td><td>2</td></tr></table>"
            b"<footer>copyright</footer></body></html>"
        ),
        max_bytes=4096,
    )

    assert "menu" not in parsed.text
    assert "copyright" not in parsed.text
    heading = next(block for block in parsed.blocks if block.kind == "heading")
    assert heading.level == 2
    assert heading.text == "FAQ"
    table = next(block for block in parsed.blocks if block.kind == "table")
    assert table.text == "a | b\n1 | 2"


def test_docx_preserves_headings_and_tables() -> None:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{namespace}"><w:body>'
        "<w:p><w:pPr><w:pStyle w:val=\"Heading1\"/></w:pPr>"
        "<w:r><w:t>退款流程</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>客户提交申请后 24 小时内处理。</w:t></w:r></w:p>"
        "<w:tbl>"
        "<w:tr><w:tc><w:p><w:r><w:t>类型</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>时限</w:t></w:r></w:p></w:tc></w:tr>"
        "<w:tr><w:tc><w:p><w:r><w:t>仅退款</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>24h</w:t></w:r></w:p></w:tc></w:tr>"
        "</w:tbl></w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)

    parsed = parse_document(
        filename="refund.docx",
        content_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        data=buffer.getvalue(),
        max_bytes=4096,
    )

    heading = next(block for block in parsed.blocks if block.kind == "heading")
    assert heading.level == 1
    assert heading.text == "退款流程"
    table = next(block for block in parsed.blocks if block.kind == "table")
    assert table.text == "类型 | 时限\n仅退款 | 24h"
