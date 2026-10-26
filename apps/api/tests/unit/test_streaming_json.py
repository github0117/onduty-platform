import json

import pytest

from ticket_agent.customer_service.streaming import iter_text_chunks
from ticket_agent.model_gateway.streaming_json import JsonStringFieldExtractor


def test_extractor_handles_chunk_boundaries_and_escapes() -> None:
    payload = json.dumps(
        {
            "text": '你好，\n世界 "引号" 和 \\ 反斜杠。',
            "claims": [{"text": "不应被流式输出", "nested": {"k": "v"}}],
            "cited_chunk_ids": ["chunk-1"],
        },
        ensure_ascii=False,
    )

    for size in (1, 2, 5, 17, 1000):
        extractor = JsonStringFieldExtractor()
        emitted = "".join(
            extractor.feed(payload[index : index + size]) for index in range(0, len(payload), size)
        )
        assert emitted == '你好，\n世界 "引号" 和 \\ 反斜杠。'
        assert extractor.target_started is True
        assert extractor.target_finished is True


def test_extractor_decodes_unicode_escapes_split_across_chunks() -> None:
    extractor = JsonStringFieldExtractor()
    emitted = "".join(
        extractor.feed(part) for part in ['{"text": "\\u4f60', "\\u597d\\n", '\\u4e16\\u754c"}']
    )

    assert emitted == "你好\n世界"


def test_extractor_ignores_nested_and_other_fields() -> None:
    extractor = JsonStringFieldExtractor()
    emitted = "".join(
        extractor.feed(part)
        for part in [
            '{"claims": [{"text": "外部"',
            '}], "text": "目标", "other": {"text": "嵌套"}}',
        ]
    )

    assert emitted == "目标"


def test_extractor_handles_text_before_nested_objects() -> None:
    extractor = JsonStringFieldExtractor()
    emitted = "".join(
        extractor.feed(part)
        for part in ['{"text": "第一段', '", "claims": [', '{"text": "其余"}]}']
    )

    assert emitted == "第一段"


@pytest.mark.parametrize("text", ["", "短", "这是一个包含标点，以及英文逗号, 的句子。"])
def test_iter_text_chunks_preserves_the_original_text(text: str) -> None:
    chunks = list(iter_text_chunks(text, target_chunks=8))

    assert "".join(chunks) == text
    if text:
        assert all(chunks)
        assert len(chunks) <= 8 * 2


def test_iter_text_chunks_stops_at_punctuation_when_possible() -> None:
    chunks = list(iter_text_chunks("第一句话。第二句话。", target_chunks=100))

    assert "".join(chunks) == "第一句话。第二句话。"
    assert chunks[0].endswith("。")


def test_iter_text_chunks_keeps_urls_and_latin_words_whole() -> None:
    text = "请提供 owner/repo 格式的 GitHub 仓库和具体问题。"
    chunks = list(iter_text_chunks(text, target_chunks=48))

    assert "".join(chunks) == text
    assert any("owner/repo" in chunk for chunk in chunks)
    assert any("GitHub" in chunk for chunk in chunks)
