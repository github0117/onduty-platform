import io
import zipfile

import pymupdf
import pytest

from ticket_agent.knowledge.document_parser import (
    DocumentParseError,
    parse_document,
    serialize_blocks,
)
from ticket_agent.knowledge.ocr import OCRResult, OCRUnavailableError


class _FakeOCR:
    name = "fake"

    def __init__(self, text: str = "", *, error: bool = False) -> None:
        self._text = text
        self._error = error

    def extract_text(self, *, data: bytes, content_type: str) -> OCRResult:
        del data, content_type
        if self._error:
            raise OCRUnavailableError("ocr boom")
        return OCRResult(text=self._text, provider=self.name, model_name="fake-model")


def _pdf_bytes(texts: list[str | None]) -> bytes:
    document = pymupdf.open()
    for text in texts:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


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


def test_parse_image_uses_ocr_and_marks_page() -> None:
    parsed = parse_document(
        filename="scan.png",
        content_type="image/png",
        data=b"\x89PNG\r\n",
        max_bytes=1024,
        ocr_provider=_FakeOCR("退款政策扫描件文字"),
    )

    assert parsed.parser_name == "fake-ocr"
    assert len(parsed.blocks) == 1
    block = parsed.blocks[0]
    assert block.kind == "image_text"
    assert block.page == 1
    assert block.ocr is True
    assert "退款政策扫描件文字" in block.text


def test_parse_image_without_ocr_provider_is_rejected() -> None:
    with pytest.raises(DocumentParseError) as error:
        parse_document(
            filename="scan.png",
            content_type="image/png",
            data=b"\x89PNG\r\n",
            max_bytes=1024,
        )

    assert error.value.code == "OCR_NOT_CONFIGURED"


def test_parse_image_ocr_failure_reports_error() -> None:
    with pytest.raises(DocumentParseError) as error:
        parse_document(
            filename="scan.jpg",
            content_type="image/jpeg",
            data=b"\xff\xd8",
            max_bytes=1024,
            ocr_provider=_FakeOCR(error=True),
        )

    assert error.value.code == "OCR_FAILED"


def test_parse_text_pdf_records_page_numbers() -> None:
    data = _pdf_bytes(
        [
            "Page one explains the refund workflow in detail.",
            "Page two lists the required evidence for the claim.",
        ]
    )

    parsed = parse_document(
        filename="policy.pdf",
        content_type="application/pdf",
        data=data,
        max_bytes=4096,
    )

    pages = {block.page for block in parsed.blocks}
    assert pages == {1, 2}
    assert all(block.ocr is False for block in parsed.blocks)


def test_parse_mixed_pdf_ocrs_only_low_text_page() -> None:
    data = _pdf_bytes(
        [
            "Page one already contains enough native text for retrieval.",
            None,
        ]
    )

    parsed = parse_document(
        filename="mixed.pdf",
        content_type="application/pdf",
        data=data,
        max_bytes=4096,
        ocr_provider=_FakeOCR("第二页扫描内容：跨境退款需人工审核"),
        ocr_min_text_chars=30,
    )

    assert parsed.parser_name == "pymupdf+fake"
    page_two = [block for block in parsed.blocks if block.page == 2]
    assert len(page_two) == 1
    assert page_two[0].ocr is True
    assert "跨境退款" in page_two[0].text
    page_one = [block for block in parsed.blocks if block.page == 1]
    assert page_one and all(block.ocr is False for block in page_one)


def test_parse_scanned_pdf_without_ocr_is_empty() -> None:
    with pytest.raises(DocumentParseError) as error:
        parse_document(
            filename="scanned.pdf",
            content_type="application/pdf",
            data=_pdf_bytes([None]),
            max_bytes=4096,
        )

    assert error.value.code == "EMPTY_DOCUMENT"


def test_parse_pdf_ocr_failure_falls_back_to_native_text() -> None:
    parsed = parse_document(
        filename="mixed.pdf",
        content_type="application/pdf",
        data=_pdf_bytes(
            [
                "Page one already contains enough native text for retrieval.",
                None,
            ]
        ),
        max_bytes=4096,
        ocr_provider=_FakeOCR(error=True),
        ocr_min_text_chars=30,
    )

    assert parsed.parser_version != "unavailable"
    assert "OCR_FAILED" in parsed.warnings
    assert [block.page for block in parsed.blocks] == [1]


def test_parse_pdf_ocr_failure_without_native_text_reports_error() -> None:
    with pytest.raises(DocumentParseError) as error:
        parse_document(
            filename="scanned.pdf",
            content_type="application/pdf",
            data=_pdf_bytes([None]),
            max_bytes=4096,
            ocr_provider=_FakeOCR(error=True),
        )

    assert error.value.code == "OCR_FAILED"


def test_serialize_blocks_keeps_page_and_ocr_flags() -> None:
    parsed = parse_document(
        filename="scan.png",
        content_type="image/png",
        data=b"\x89PNG\r\n",
        max_bytes=1024,
        ocr_provider=_FakeOCR("扫描文字"),
    )
    payload = serialize_blocks(parsed.blocks, parsed.warnings)

    block = payload["blocks"][0]
    assert block["page"] == 1
    assert block["ocr"] is True
    assert block["kind"] == "image_text"
