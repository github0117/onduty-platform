from ticket_agent.knowledge.chunking import chunk_blocks


def test_sections_follow_heading_hierarchy() -> None:
    drafts = chunk_blocks(
        [
            {"kind": "heading", "text": "退款政策", "level": 1},
            {"kind": "paragraph", "text": "签收后七天内可以申请退款。"},
            {"kind": "heading", "text": "跨境订单", "level": 2},
            {"kind": "paragraph", "text": "跨境订单不支持无理由退款。"},
            {"kind": "heading", "text": "发票", "level": 1},
            {"kind": "paragraph", "text": "发票在确认收货后开具。"},
        ]
    )

    assert [draft.section_path for draft in drafts] == [
        ("退款政策",),
        ("退款政策", "跨境订单"),
        ("发票",),
    ]
    assert drafts[0].embedding_text.startswith("退款政策\n")
    assert drafts[0].content == "签收后七天内可以申请退款。"


def test_table_is_atomic_and_never_merged() -> None:
    table_text = "\n".join(
        f"第{index}行 | 内容{index}" for index in range(200)
    )
    drafts = chunk_blocks(
        [
            {"kind": "heading", "text": "价格表", "level": 1},
            {"kind": "paragraph", "text": "以下为价格。"},
            {"kind": "table", "text": table_text},
            {"kind": "paragraph", "text": "价格含税。"},
        ],
        target_chars=200,
        max_chars=500,
    )

    assert len(drafts) == 3
    assert drafts[1].content == table_text
    assert drafts[1].block_kinds == ("table",)
    assert drafts[2].content == "价格含税。"


def test_short_paragraphs_are_packed_up_to_target() -> None:
    drafts = chunk_blocks(
        [
            {"kind": "paragraph", "text": "第一段内容。"},
            {"kind": "paragraph", "text": "第二段内容。"},
        ],
        target_chars=50,
        max_chars=100,
    )

    assert len(drafts) == 1
    assert drafts[0].content == "第一段内容。\n第二段内容。"


def test_long_paragraph_is_split_within_max_chars() -> None:
    sentence = "这是一句用于测试分块长度限制的中文内容。"
    drafts = chunk_blocks(
        [{"kind": "paragraph", "text": sentence * 20}],
        target_chars=40,
        max_chars=80,
    )

    assert len(drafts) > 1
    assert all(len(draft.content) <= 80 for draft in drafts)
    assert "".join(draft.content for draft in drafts) == sentence * 20


def test_chunk_without_heading_has_no_embedding_prefix() -> None:
    drafts = chunk_blocks([{"kind": "paragraph", "text": "没有标题的内容。"}])

    assert drafts[0].section_path == ()
    assert drafts[0].embedding_text == "没有标题的内容。"


def test_empty_blocks_return_no_chunks() -> None:
    assert chunk_blocks([{"kind": "heading", "text": "只有标题", "level": 1}]) == []
