from ticket_agent.knowledge.text_cleaning import (
    clean_pdf_pages,
    clean_text,
    normalize_whitespace,
    strip_repeated_page_artifacts,
)


def test_normalize_whitespace_removes_zero_width_and_nbsp() -> None:
    source = "退款政策\u200b说明\u00a0第一行\n\n\n\n第二行"
    cleaned = normalize_whitespace(source)

    assert "\u200b" not in cleaned
    assert "\u00a0" not in cleaned
    assert cleaned == "退款政策说明 第一行\n\n第二行"


def test_clean_text_drops_explicit_page_numbers() -> None:
    text, warnings = clean_text("第一段内容足够长可以保留。\n第 2 页\n第二段内容。\n3/10")

    assert "第 2 页" not in text
    assert "3/10" not in text
    assert "第一段内容足够长可以保留。" in text
    assert warnings == []


def test_clean_text_merges_wrapped_cjk_lines() -> None:
    text, _ = clean_text(
        "员工在客户提出退款申请时应当在两个工作日内完成\n"
        "审核并给出明确答复。",
        merge_wrapped=True,
    )

    assert text == "员工在客户提出退款申请时应当在两个工作日内完成审核并给出明确答复。"


def test_clean_text_does_not_merge_list_items() -> None:
    text, _ = clean_text("第一步需要核对订单信息并且确认支付状态是否正常\n1. 打开订单详情")

    assert "1. 打开订单详情" in text.splitlines()


def test_clean_text_merges_ascii_hyphen_breaks() -> None:
    text, _ = clean_text("The refund policy is docu-\nmented in the handbook.")

    assert "documented" in text


def test_strip_repeated_page_artifacts_removes_headers_and_footers() -> None:
    pages = [
        "内部资料 版权所有\n正文一第一句。\n正文一第二句。\n正文一第三句。\n1",
        "内部资料 版权所有\n正文二第一句。\n正文二第二句。\n正文二第三句。\n2",
        "内部资料 版权所有\n正文三第一句。\n正文三第二句。\n正文三第三句。\n3",
        "内部资料 版权所有\n正文四第一句。\n正文四第二句。\n正文四第三句。\n4",
    ]

    stripped = strip_repeated_page_artifacts(pages)

    assert all("内部资料 版权所有" not in page for page in stripped)
    assert stripped[0].splitlines()[0] == "正文一第一句。"


def test_clean_pdf_pages_drops_repeated_headers_and_page_numbers() -> None:
    text, _ = clean_pdf_pages(
        [
            "员工手册\n第一章 总则\n本手册适用于全体员工。\n1",
            "员工手册\n第二章 考勤\n员工应当按时打卡。\n2",
            "员工手册\n第三章 请假\n请假需要提前申请。\n3",
        ]
    )

    assert "员工手册" not in text
    assert "第一章 总则" in text
    assert "\n1\n" not in f"\n{text}\n"


def test_quality_warnings_flag_mojibake() -> None:
    _, warnings = clean_text("退款政策" + "�" * 20)

    assert "PARSE_QUALITY_LOW" in warnings
